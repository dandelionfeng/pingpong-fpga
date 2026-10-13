"""Roboflow tableTennis v2 ZIP 的获取、解压、审计与二分类转换。

流程（对应方案 E/G/H/I）
------------------------
1. :func:`ensure_raw_dataset` 定位/解压 RAW v2（绝不改动 RAW 内容）；
2. :func:`audit_raw_dataset` 解析 **实际存在的** ``data.yaml``，报告
   ``class_id → class_name``，并据此查找 ball/racket 的真实 id（不假设 0/4）；
3. :func:`convert_to_ball_racket` 生成 `tabletennis_ball_racket_v1`：
   保留原始 train/valid/test 划分、保留全部图片（无目标者作为合法负样本）、
   只保留 ball→0 / racket→1 的标签。

安全约束
--------
* API key 只从环境变量读，不落盘、不打印；
* ZIP 解压做 Zip Slip 防护；
* 不改写 RAW，转换输出到全新目录。
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import CLASS_BALL, CLASS_RACKET
from .config import (
    BALL_RACKET_NAMES as _BR_NAMES,
    DOWNLOAD_ZIP_BASENAMES,
    EXPECTED_V2_CLASSES,
    EXPECTED_V2_SPLITS,
    EXPECTED_V2_TOTAL,
    PATHS,
    RAW_DIRNAME,
    ROBOFLOW_AUTHOR,
    ROBOFLOW_DATASET_URL,
    ROBOFLOW_FORMAT,
    ROBOFLOW_LICENSE,
    ROBOFLOW_MODEL_ID,
    ROBOFLOW_PROJECT,
    ROBOFLOW_UNIVERSE_URL,
    ROBOFLOW_VERSION,
    ROBOFLOW_WORKSPACE,
    WAITING_FOR_ZIP_TOKEN,
    download_date,
    find_source_zip,
    roboflow_api_key,
)
from .yolo_io import yolo_line_is_valid, yolo_norm_to_pixel

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
# 原始 split 名称 → 输出 split 名称（保持对应关系，不重新随机划分）
SPLIT_ALIASES = {"train": "train", "valid": "val", "val": "val", "test": "test"}


class DataPrepError(RuntimeError):
    """数据准备阶段的硬失败（必须停下来人工介入）。"""


class WaitingForZip(RuntimeError):
    """唯一允许停下来汇报用户的情况。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.token = WAITING_FOR_ZIP_TOKEN


# ================================================================ 工具
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def find_data_yaml(root: Path) -> Path:
    """在解压结果中**自动寻找** ``data.yaml``，不假设层级。

    多个候选时优先选择同级含 ``train``/``valid`` 图像目录的那个。
    """
    candidates = sorted(Path(root).rglob("data.yaml"))
    candidates = [p for p in candidates if "__MACOSX" not in p.parts]
    if not candidates:
        raise DataPrepError(f"no data.yaml found under {root}")
    if len(candidates) == 1:
        return candidates[0]

    def score(path: Path) -> tuple[int, int]:
        parent = path.parent
        has_dirs = sum(
            1 for name in ("train", "valid", "val", "test") if (parent / name).is_dir()
        )
        has_images = sum(
            1 for name in ("train", "valid", "val", "test") if (parent / "images" / name).is_dir()
        )
        return (has_images, has_dirs)

    return max(candidates, key=score)


def load_data_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise DataPrepError(f"data.yaml is not a mapping: {path}")
    return payload


def normalize_names(raw_names) -> dict[int, str]:
    """把 ``names``（list 或 dict）统一成 ``{int: str}``。"""
    if isinstance(raw_names, dict):
        return {int(key): str(value) for key, value in raw_names.items()}
    if isinstance(raw_names, (list, tuple)):
        return {index: str(value) for index, value in enumerate(raw_names)}
    raise DataPrepError(f"unsupported names field: {type(raw_names)!r}")


def lookup_class_id(names: dict[int, str], wanted: str) -> int:
    """按**真实 names** 反查类别 id（大小写与空白鲁棒）。"""
    target = wanted.strip().lower()
    matches = [cid for cid, name in names.items() if str(name).strip().lower() == target]
    if not matches:
        raise DataPrepError(
            f"class {wanted!r} not present in data.yaml names={names}"
        )
    if len(matches) > 1:
        raise DataPrepError(f"class {wanted!r} is ambiguous in names={names}")
    return matches[0]


def resolve_split_dir(root: Path, split: str) -> Path | None:
    """定位 split 的图像目录（Roboflow 导出为 ``<split>/images``）。"""
    for name in {split, "val" if split == "valid" else split}:
        for candidate in (
            root / name / "images",
            root / "images" / name,
            root / name,
        ):
            if candidate.is_dir():
                return candidate
    return None


def resolve_label_dir(root: Path, split: str) -> Path | None:
    for name in {split, "val" if split == "valid" else split}:
        for candidate in (
            root / name / "labels",
            root / "labels" / name,
            root / name.replace("images", "labels"),
        ):
            if candidate.is_dir():
                return candidate
    return None


def list_images(directory: Path) -> list[Path]:
    if directory is None or not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda p: p.name,
    )


# ================================================================ 解压
def safe_extract(zip_path: Path, target: Path) -> list[Path]:
    """解压 ZIP（Zip Slip 防护 + 跳过垃圾条目），返回解出的文件列表。"""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            name = member.filename
            if member.is_dir():
                continue
            if name.startswith("__MACOSX/") or Path(name).name.startswith("._"):
                continue
            destination = (target / name).resolve()
            if not str(destination).startswith(str(target_resolved)):
                raise DataPrepError(f"unsafe zip member escapes target: {name}")
            archive.extract(member, target)
            extracted.append(destination)
    return extracted


def download_with_roboflow_sdk(target_dir: Path, api_key: str) -> Path:
    """官方 Roboflow SDK 下载（key 只在内存中传递，绝不写入文件或日志）。"""
    try:
        from roboflow import Roboflow  # type: ignore
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise DataPrepError("roboflow SDK is not installed") from exc

    rf = Roboflow(api_key=api_key)
    project = rf.workspace(ROBOFLOW_WORKSPACE).project(ROBOFLOW_PROJECT)
    version = project.version(ROBOFLOW_VERSION)
    target_dir.mkdir(parents=True, exist_ok=True)
    dataset = version.download(ROBOFLOW_FORMAT, location=str(target_dir), overwrite=True)
    return Path(getattr(dataset, "location", target_dir))


def try_auto_download(raw_dir: Path) -> Path | None:
    """自动路线：有 ``ROBOFLOW_API_KEY`` 才尝试；失败返回 ``None``（转人工 fallback）。"""
    api_key = roboflow_api_key()
    if not api_key:
        print("[download] ROBOFLOW_API_KEY is not set -> manual ZIP fallback")
        return None
    print("[download] ROBOFLOW_API_KEY detected (value never printed); trying Roboflow SDK")
    staging = raw_dir / "_sdk_download"
    try:
        location = download_with_roboflow_sdk(staging, api_key)
    except Exception as exc:  # noqa: BLE001 - 任何下载失败都走 fallback
        print(f"[download] SDK download failed: {type(exc).__name__}: {exc}")
        return None
    data_yaml = find_data_yaml(location if location.is_dir() else staging)
    print(f"[download] SDK download ok, data.yaml at {data_yaml}")
    return data_yaml


# ================================================================ RAW 获取
def ensure_raw_dataset(raw_dir: Path | None = None, force: bool = False) -> Path:
    """确保 RAW v2 已就位，返回其 ``data.yaml``。

    顺序：已有 RAW → 环境变量 API key 自动下载 → downloads/ 中的 ZIP → 抛
    :class:`WaitingForZip`（附带人工步骤）。
    """
    raw = Path(raw_dir) if raw_dir is not None else PATHS.raw_dir
    raw.mkdir(parents=True, exist_ok=True)

    existing = sorted(raw.rglob("data.yaml"))
    existing = [p for p in existing if "_sdk_download" not in p.parts or force]
    if existing and not force:
        data_yaml = find_data_yaml(raw)
        print(f"[raw] reuse existing dataset: {data_yaml}")
        return data_yaml

    result = try_auto_download(raw)
    if result is not None:
        return result

    zip_path = find_source_zip(PATHS.downloads_dir)
    if zip_path is None:
        raise WaitingForZip(manual_zip_instructions())
    print(f"[download] found manual ZIP: {zip_path.name} ({zip_path.stat().st_size} bytes)")
    print(f"[download] extracting into {raw} ...")
    safe_extract(zip_path, raw)
    data_yaml = find_data_yaml(raw)
    print(f"[download] extracted, data.yaml at {data_yaml}")
    return data_yaml


def manual_zip_instructions(downloads_dir: Path | None = None) -> str:
    target = Path(downloads_dir) if downloads_dir is not None else PATHS.downloads_dir
    preferred = target / DOWNLOAD_ZIP_BASENAMES[0]
    return f"""{WAITING_FOR_ZIP_TOKEN}

缺少 Roboflow tableTennis v2 的 YOLOv8 ZIP，且本机没有 ROBOFLOW_API_KEY。
请按下面 5 步手动下载（不要换数据集、不要用 v1）：

1) 打开网址
   {ROBOFLOW_DATASET_URL}

2) 点击右上角 "Download Dataset"（若弹出登录，用任意免费账号登录即可）

3) 在弹出的格式列表里选择 "YOLOv8"
   - Format: YOLOv8
   - 不要选 COCO / VOC / TFRecord
   - 确认页面顶部显示的是 Version 2（左侧版本号是 2）
   - 不要勾选任何 "preprocessing / augmentation"（v2 本身就是 None/None）

4) 下载得到的 ZIP 放到这个目录（目录已创建好）
   {target}
   建议命名为：
   {preferred.name}

5) 放好后告诉我 "ZIP 已放好"，我执行：
   .\\.venv\\c-detector\\Scripts\\python.exe vision\\c_perception_v2\\prepare_tabletennis_br.py --auto
   程序会自动发现 ZIP、解压、审计、转换，无需其它手工步骤。

校验预期（放好后程序会自动断言，不符即停止训练）：
   total = {EXPECTED_V2_TOTAL}   train = {EXPECTED_V2_SPLITS['train']}
   valid = {EXPECTED_V2_SPLITS['valid']}   test = {EXPECTED_V2_SPLITS['test']}
   original classes = {list(EXPECTED_V2_CLASSES)}
"""


# ================================================================ 审计
@dataclass
class SplitAudit:
    split: str
    images: int = 0
    label_files: int = 0
    ball_instances: int = 0
    racket_instances: int = 0
    images_with_ball: int = 0
    images_with_racket: int = 0
    zero_target_images: int = 0
    dropped_instances: int = 0
    missing_labels: int = 0
    orphan_labels: int = 0
    invalid_labels: int = 0
    unreadable_images: int = 0
    bbox_out_of_bounds: int = 0
    bbox_zero_area: int = 0
    nan_values: int = 0
    duplicate_images: int = 0
    class_instance_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "split": self.split,
            "images": self.images,
            "label_files": self.label_files,
            "ball_instances": self.ball_instances,
            "racket_instances": self.racket_instances,
            "images_with_ball": self.images_with_ball,
            "images_with_racket": self.images_with_racket,
            "zero_target_images": self.zero_target_images,
            "dropped_instances": self.dropped_instances,
            "missing_labels": self.missing_labels,
            "orphan_labels": self.orphan_labels,
            "invalid_labels": self.invalid_labels,
            "unreadable_images": self.unreadable_images,
            "bbox_out_of_bounds": self.bbox_out_of_bounds,
            "bbox_zero_area": self.bbox_zero_area,
            "nan_values": self.nan_values,
            "duplicate_images": self.duplicate_images,
            "class_instance_counts": self.class_instance_counts,
        }


@dataclass
class RawAudit:
    data_yaml: Path
    names: dict[int, str]
    ball_id: int
    racket_id: int
    splits: list[SplitAudit]
    total_images: int
    duplicate_groups: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "data_yaml": str(self.data_yaml),
            "names": {str(k): v for k, v in sorted(self.names.items())},
            "ball_class_id": self.ball_id,
            "racket_class_id": self.racket_id,
            "total_images": self.total_images,
            "splits": [s.to_dict() for s in self.splits],
            "duplicate_groups": self.duplicate_groups,
        }


def read_yolo_label_file(label_path: Path) -> tuple[list[tuple[int, float, float, float, float]], list[str]]:
    """读取 YOLO 标签，返回 ``(instances, errors)``；instances 为 5 元组列表。"""
    instances: list[tuple[int, float, float, float, float]] = []
    errors: list[str] = []
    if not label_path.is_file():
        return instances, errors
    for line_number, line in enumerate(
        label_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) != 5:
            errors.append(f"{label_path.name}:{line_number} expected 5 columns, got {len(parts)}")
            continue
        try:
            values = [float(v) for v in parts]
        except ValueError:
            errors.append(f"{label_path.name}:{line_number} non-numeric field")
            continue
        class_id = int(values[0])
        cx, cy, w, h = values[1:]
        instances.append((class_id, cx, cy, w, h))
    return instances, errors


def audit_raw_dataset(data_yaml: Path) -> RawAudit:
    """解析 RAW：真实 names、真实 ball/racket id、每个 split 的实例统计。"""
    payload = load_data_yaml(data_yaml)
    names = normalize_names(payload.get("names"))
    ball_id = lookup_class_id(names, "ball")
    racket_id = lookup_class_id(names, "racket")
    root = data_yaml.parent

    splits: list[SplitAudit] = []
    hash_to_names: dict[str, list[str]] = {}

    declared = payload.get("train"), payload.get("val") or payload.get("valid"), payload.get("test")
    split_names: list[str] = []
    for candidate in ("train", "valid", "test"):
        if resolve_split_dir(root, candidate) is not None:
            split_names.append(candidate)
    if not split_names:
        for entry in declared:
            if entry:
                split_names.append("train")
                break
        if not split_names:
            raise DataPrepError(f"cannot determine splits from data.yaml: {payload}")

    for split in split_names:
        image_dir = resolve_split_dir(root, split)
        label_dir = resolve_label_dir(root, split)
        audit = SplitAudit(split=split)
        images = list_images(image_dir) if image_dir else []
        audit.images = len(images)
        labels = sorted(label_dir.glob("*.txt")) if label_dir and label_dir.is_dir() else []
        audit.label_files = len(labels)
        label_by_stem = {p.stem: p for p in labels}
        seen_stems: set[str] = set()

        from PIL import Image  # 局部导入：纯几何测试不强依赖

        for image_path in images:
            seen_stems.add(image_path.stem)
            label_path = label_by_stem.get(image_path.stem)
            if label_path is None:
                audit.missing_labels += 1
            try:
                with Image.open(image_path) as handle:
                    width, height = handle.size
                    handle.verify()
            except Exception:  # noqa: BLE001
                audit.unreadable_images += 1
                continue

            digest = sha256_file(image_path)
            hash_to_names.setdefault(digest, []).append(f"{split}/{image_path.name}")

            instances, errors = read_yolo_label_file(label_path) if label_path else ([], [])
            if errors:
                audit.invalid_labels += len(errors)
                audit.notes.extend(errors[:5])
            has_ball = has_racket = False
            for class_id, cx, cy, w, h in instances:
                name = names.get(class_id, f"<unknown:{class_id}>")
                audit.class_instance_counts[name] = audit.class_instance_counts.get(name, 0) + 1
                if w <= 0 or h <= 0:
                    audit.bbox_zero_area += 1
                if not all(isinstance(v, float) and v == v for v in (cx, cy, w, h)):
                    audit.nan_values += 1
                box = yolo_norm_to_pixel(class_id, cx, cy, w, h, width, height)
                if not box.is_inside(width, height):
                    audit.bbox_out_of_bounds += 1
                if class_id == ball_id:
                    audit.ball_instances += 1
                    has_ball = True
                elif class_id == racket_id:
                    audit.racket_instances += 1
                    has_racket = True
                else:
                    audit.dropped_instances += 1
            audit.images_with_ball += int(has_ball)
            audit.images_with_racket += int(has_racket)
            audit.zero_target_images += int(not (has_ball or has_racket))

        orphans = [stem for stem in label_by_stem if stem not in seen_stems]
        audit.orphan_labels = len(orphans)
        if orphans:
            audit.notes.append(f"orphan labels e.g. {orphans[:5]}")
        splits.append(audit)

    duplicate_groups = [names_list for names_list in hash_to_names.values() if len(names_list) > 1]
    total = sum(s.images for s in splits)
    result = RawAudit(
        data_yaml=data_yaml,
        names=names,
        ball_id=ball_id,
        racket_id=racket_id,
        splits=splits,
        total_images=total,
        duplicate_groups=duplicate_groups,
    )
    # 重复图跨 split 归属：把数量落到 split 上
    for group in duplicate_groups:
        for entry in group:
            split = entry.split("/", 1)[0]
            for audit in result.splits:
                if audit.split == split:
                    audit.duplicate_images += len(group) - 1
    return result


def assert_expected_v2(audit: RawAudit) -> list[str]:
    """校验下载到的确实是 v2（1480 张、7 类、no preprocessing）。

    返回告警列表；总量不符直接抛 :class:`DataPrepError`（禁止“稀里糊涂开始训练”）。
    """
    warnings: list[str] = []
    actual = {s.split: s.images for s in audit.splits}
    if audit.total_images != EXPECTED_V2_TOTAL:
        raise DataPrepError(
            "dataset size mismatch: got "
            f"{audit.total_images} images (per split: {actual}), expected {EXPECTED_V2_TOTAL}. "
            "Stop training and check: did you download v1? did Roboflow auto-augment? wrong version?"
        )
    for split, expected in EXPECTED_V2_SPLITS.items():
        got = actual.get(split)
        if got != expected:
            if split == "valid" and actual.get("val") == expected:
                continue
            warnings.append(f"split {split}: got {got}, public page says {expected}")
    present = set(audit.names.values())
    missing = [c for c in EXPECTED_V2_CLASSES if c not in present]
    extra = sorted(present - set(EXPECTED_V2_CLASSES))
    if missing:
        warnings.append(f"classes missing vs public page: {missing}")
    if extra:
        warnings.append(f"extra classes vs public page: {extra}")
    return warnings


# ================================================================ 转换
@dataclass
class ConversionStats:
    output_dir: Path
    data_yaml: Path
    ball_id_source: int
    racket_id_source: int
    splits: list[SplitAudit]
    copies: list[dict]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "output_dir": str(self.output_dir),
            "data_yaml": str(self.data_yaml),
            "class_order": {str(k): v for k, v in _BR_NAMES.items()},
            "source_class_ids": {"ball": self.ball_id_source, "racket": self.racket_id_source},
            "splits": [s.to_dict() for s in self.splits],
            "warnings": self.warnings,
            "copies": self.copies,
        }


def write_br_data_yaml(output_dir: Path) -> Path:
    """生成绝对路径的 ``data.yaml``，解决 Ultralytics 的 datasets_dir 跑偏问题。"""
    output_dir = Path(output_dir).resolve()
    yaml_path = output_dir / "data.yaml"
    payload = {
        "path": output_dir.as_posix(),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "nc": 2,
        "names": {0: "ball", 1: "racket"},
    }
    header = (
        "# 自动生成：tableTennis v2 (Roboflow, yolo class, CC BY 4.0) → ball/racket 二分类\n"
        "# path 必须是绝对路径（Ultralytics 会把相对 path 拼到全局 datasets_dir）。\n"
        "# 不要手工编辑：由 vision/c_perception_v2/prepare_tabletennis_br.py 重新生成。\n"
    )
    with open(yaml_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(header)
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
    return yaml_path


def convert_to_ball_racket(
    raw_data_yaml: Path,
    output_dir: Path | None = None,
    clean: bool = False,
) -> ConversionStats:
    """RAW → ``tabletennis_ball_racket_v1``（RAW 只读）。"""
    raw_data_yaml = Path(raw_data_yaml)
    raw_root = raw_data_yaml.parent
    payload = load_data_yaml(raw_data_yaml)
    names = normalize_names(payload.get("names"))
    ball_id = lookup_class_id(names, "ball")
    racket_id = lookup_class_id(names, "racket")

    out = Path(output_dir) if output_dir is not None else PATHS.br_dir
    if clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    copies: list[dict] = []
    split_stats: list[SplitAudit] = []
    hash_to_names: dict[str, list[str]] = {}

    for source_split in ("train", "valid", "test"):
        target_split = SPLIT_ALIASES[source_split]
        image_dir = resolve_split_dir(raw_root, source_split)
        if image_dir is None:
            continue
        label_dir = resolve_label_dir(raw_root, source_split)
        label_by_stem = (
            {p.stem: p for p in label_dir.glob("*.txt")} if label_dir and label_dir.is_dir() else {}
        )
        stats = SplitAudit(split=target_split)
        images = list_images(image_dir)
        stats.images = len(images)
        stats.label_files = len(label_by_stem)

        for image_path in images:
            destination_image = out / "images" / target_split / image_path.name
            shutil.copy2(image_path, destination_image)
            try:
                from PIL import Image

                with Image.open(image_path) as handle:
                    width, height = handle.size
            except Exception:  # noqa: BLE001
                stats.unreadable_images += 1
                continue

            digest = sha256_file(image_path)
            hash_to_names.setdefault(digest, []).append(f"{target_split}/{image_path.name}")

            source_label = label_by_stem.get(image_path.stem)
            kept_lines: list[str] = []
            has_ball = has_racket = False
            if source_label is not None:
                for line_number, line in enumerate(
                    source_label.read_text(encoding="utf-8", errors="replace").splitlines(),
                    start=1,
                ):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split()
                    ok, reason = _validate_source_line(parts)
                    if not ok:
                        stats.invalid_labels += 1
                        stats.notes.append(f"{source_label.name}:{line_number} {reason}")
                        continue
                    class_id = int(float(parts[0]))
                    if class_id not in (ball_id, racket_id):
                        stats.dropped_instances += 1
                        continue
                    cx, cy, w, h = (float(v) for v in parts[1:])
                    if w <= 0 or h <= 0:
                        stats.bbox_zero_area += 1
                        continue
                    from .yolo_io import yolo_norm_to_pixel as _to_px

                    box = _to_px(class_id, cx, cy, w, h, width, height)
                    if not box.is_inside(width, height):
                        stats.bbox_out_of_bounds += 1
                        continue
                    target_class = CLASS_BALL if class_id == ball_id else CLASS_RACKET
                    kept_lines.append(
                        f"{target_class} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"
                    )
                    if target_class == CLASS_BALL:
                        stats.ball_instances += 1
                        has_ball = True
                    else:
                        stats.racket_instances += 1
                        has_racket = True
            else:
                stats.missing_labels += 1

            # 无目标的图片保留为合法 negative image，标签文件为空
            label_out = out / "labels" / target_split / f"{image_path.stem}.txt"
            label_out.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")

            stats.images_with_ball += int(has_ball)
            stats.images_with_racket += int(has_racket)
            stats.zero_target_images += int(not (has_ball or has_racket))
            copies.append(
                {
                    "split": target_split,
                    "image": f"images/{target_split}/{image_path.name}",
                    "label": f"labels/{target_split}/{label_out.name}",
                    "source_image": str(image_path.relative_to(raw_root).as_posix()),
                    "width": width,
                    "height": height,
                    "sha256": digest,
                    "ball": int(has_ball),
                    "racket": int(has_racket),
                }
            )

        stats.class_instance_counts = {
            "ball": stats.ball_instances,
            "racket": stats.racket_instances,
        }
        split_stats.append(stats)

    duplicate_groups = [v for v in hash_to_names.values() if len(v) > 1]
    for group in duplicate_groups:
        for entry in group:
            split = entry.split("/", 1)[0]
            for stats in split_stats:
                if stats.split == split:
                    stats.duplicate_images += len(group) - 1

    yaml_path = write_br_data_yaml(out)
    return ConversionStats(
        output_dir=out,
        data_yaml=yaml_path,
        ball_id_source=ball_id,
        racket_id_source=racket_id,
        splits=split_stats,
        copies=copies,
    )


def _validate_source_line(parts: list[str]) -> tuple[bool, str]:
    if len(parts) != 5:
        return False, f"expected 5 columns, got {len(parts)}"
    try:
        values = [float(v) for v in parts]
    except ValueError:
        return False, "non-numeric field"
    class_id = int(values[0])
    cx, cy, w, h = values[1:]
    if any(v != v or v in (float("inf"), float("-inf")) for v in (cx, cy, w, h)):
        return False, "NaN/Inf value"
    if class_id < 0:
        return False, f"negative class id {class_id}"
    if w <= 0 or h <= 0:
        return False, "zero-area box"
    if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
        return False, f"center out of [0,1]: {cx},{cy}"
    if not (0.0 < w <= 1.0 and 0.0 < h <= 1.0):
        return False, f"size out of (0,1]: {w},{h}"
    return True, ""


# ================================================================ 清单与记录
def write_manifest_csv(stats: ConversionStats, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "split",
        "image",
        "label",
        "source_image",
        "width",
        "height",
        "sha256",
        "ball",
        "racket",
    ]
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in stats.copies:
            writer.writerow(row)
    return path


def write_source_md(stats: ConversionStats, raw_audit: RawAudit, path: Path) -> Path:
    """记录公开数据源，供比赛报告 / 论文答辩引用。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 公开数据源记录（tableTennis v2）",
        "",
        f"- dataset name: `{ROBOFLOW_PROJECT}`",
        f"- dataset author: {ROBOFLOW_AUTHOR}",
        f"- Roboflow project URL: {ROBOFLOW_UNIVERSE_URL}",
        f"- Roboflow dataset (version) URL: {ROBOFLOW_DATASET_URL}",
        f"- Roboflow model id (仅参考，未使用): `{ROBOFLOW_MODEL_ID}`",
        f"- version: {ROBOFLOW_VERSION}",
        f"- license: {ROBOFLOW_LICENSE}",
        f"- download format: {ROBOFLOW_FORMAT}",
        f"- download date: {download_date()}",
        f"- downloaded at (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "- preprocessing (公开页面): None",
        "- augmentation (公开页面): None",
        "",
        "## 原始类别列表（来自实际下载的 data.yaml，非假设）",
        "",
        "| original class_id | class_name |",
        "| --- | --- |",
    ]
    for class_id, name in sorted(raw_audit.names.items()):
        lines.append(f"| {class_id} | {name} |")
    lines += [
        "",
        "## 本轮保留的类别映射",
        "",
        f"- `{raw_audit.names[raw_audit.ball_id]}` (original id {raw_audit.ball_id}) → **0 ball**",
        f"- `{raw_audit.names[raw_audit.racket_id]}` (original id {raw_audit.racket_id}) → **1 racket**",
        "- 其余类别（table / player / net / scoreboard / umpire）丢弃标签，图片保留为合法负样本",
        "- 本方案 **不再训练 hand / toss_hand / racket_hand**，也不判断哪只手是持拍手",
        "",
        "## 引用格式建议",
        "",
        f"> {ROBOFLOW_AUTHOR}, \"{ROBOFLOW_PROJECT}\" (version {ROBOFLOW_VERSION}), "
        f"Roboflow Universe, {ROBOFLOW_LICENSE}. {ROBOFLOW_UNIVERSE_URL}",
        "",
        "## 注意",
        "",
        "- 公开页面的 mAP50 87.4% / Precision 92.0% / Recall 85.6% 是 **Roboflow 页面指标**，",
        "  不是本项目模型的指标。本项目模型指标一律由 `eval_ball_racket.py` 在 v2 test split 上重测。",
        "- 本项目训练与推理不依赖 Roboflow 云端 API；云端只用于一次性获取数据。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_dataset_card(stats: ConversionStats, raw_audit: RawAudit, path: Path) -> Path:
    path = Path(path)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw_dataset": raw_audit.to_dict(),
        "conversion": stats.to_dict(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ================================================================ CLI 辅助
def print_raw_audit(audit: RawAudit) -> None:
    print("=" * 78)
    print("RAW AUDIT (tableTennis v2)")
    print("=" * 78)
    print(f"data.yaml          : {audit.data_yaml}")
    print(f"total images       : {audit.total_images}")
    print("names (真实 class_id → class_name):")
    for class_id, name in sorted(audit.names.items()):
        print(f"  {class_id:>2} : {name}")
    print(f"ball   original id : {audit.ball_id}  ({audit.names[audit.ball_id]})")
    print(f"racket original id : {audit.racket_id}  ({audit.names[audit.racket_id]})")
    print("-" * 78)
    header = (
        f"{'split':<7}{'images':>8}{'ball_inst':>11}{'racket_inst':>13}"
        f"{'img_ball':>10}{'img_racket':>12}{'zero_tgt':>10}{'dropped':>9}"
    )
    print(header)
    for stats in audit.splits:
        print(
            f"{stats.split:<7}{stats.images:>8}{stats.ball_instances:>11}"
            f"{stats.racket_instances:>13}{stats.images_with_ball:>10}"
            f"{stats.images_with_racket:>12}{stats.zero_target_images:>10}"
            f"{stats.dropped_instances:>9}"
        )
    print("-" * 78)
    for stats in audit.splits:
        print(
            f"[{stats.split}] missing_labels={stats.missing_labels} "
            f"orphan_labels={stats.orphan_labels} invalid_labels={stats.invalid_labels} "
            f"unreadable={stats.unreadable_images} oob={stats.bbox_out_of_bounds} "
            f"zero_area={stats.bbox_zero_area} duplicates={stats.duplicate_images}"
        )
    if audit.duplicate_groups:
        print(f"duplicate groups   : {len(audit.duplicate_groups)} (跨 split / 同 split 完全同图)")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="获取/审计 tableTennis v2 并生成 ball+racket 二分类数据集"
    )
    parser.add_argument("--auto", action="store_true", help="自动：有 RAW 则复用，有 ZIP 则解压")
    parser.add_argument("--raw-data-yaml", type=Path, default=None, help="直接指定 RAW data.yaml")
    parser.add_argument("--out-dir", type=Path, default=None, help="BR 数据集输出目录")
    parser.add_argument("--clean", action="store_true", help="转换前清空 BR 输出目录")
    parser.add_argument("--skip-expected-check", action="store_true", help="跳过 1480 张一致性校验")
    parser.add_argument("--force-redownload", action="store_true", help="忽略已有 RAW，重新解压/下载")
    args = parser.parse_args(argv)

    try:
        data_yaml = (
            Path(args.raw_data_yaml)
            if args.raw_data_yaml
            else ensure_raw_dataset(force=args.force_redownload)
        )
    except WaitingForZip as exc:
        print(exc)
        return 2

    audit = audit_raw_dataset(data_yaml)
    print_raw_audit(audit)
    if not args.skip_expected_check:
        warnings = assert_expected_v2(audit)
        for warning in warnings:
            print(f"[WARN] {warning}")
        print("[check] size matches the public v2 page (1480 images)")

    stats = convert_to_ball_racket(data_yaml, args.out_dir, clean=args.clean)
    print("-" * 78)
    print("CONVERSION → ball/racket 二分类")
    print(f"output   : {stats.output_dir}")
    print(f"data.yaml: {stats.data_yaml}")
    header = (
        f"{'split':<7}{'images':>8}{'ball':>8}{'racket':>8}"
        f"{'img_ball':>10}{'img_racket':>12}{'zero_tgt':>10}"
    )
    print(header)
    for split in stats.splits:
        print(
            f"{split.split:<7}{split.images:>8}{split.ball_instances:>8}"
            f"{split.racket_instances:>8}{split.images_with_ball:>10}"
            f"{split.images_with_racket:>12}{split.zero_target_images:>10}"
        )

    manifest = write_manifest_csv(stats, stats.output_dir / "manifest.csv")
    source_md = write_source_md(stats, audit, stats.output_dir / "SOURCE.md")
    card = write_dataset_card(stats, audit, stats.output_dir / "dataset_card.json")
    print(f"manifest : {manifest}")
    print(f"SOURCE.md: {source_md}")
    print(f"card     : {card}")
    print("=" * 78)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
