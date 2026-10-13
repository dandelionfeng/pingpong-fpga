"""BNDSTT 域内 fine-tune V1：确定性选池（80 张）。

目标
----
从 BNDSTT 现有 280 帧中选 80 帧做**人工修正**，用于 ball+racket 域内 fine-tune。

硬约束
------
* **不得使用 quick_test**（与 quick_test session 零重叠，构建时断言）；
* **不得改动 frozen benchmark** ``BNDSTT_30_V1``：这 30 张从池子里排除；
* **不得使用 BNDSTT_30 的任何帧**（避免训练-评测泄漏）；
* 选择确定性：固定 SEED，用 ``sha256(seed:image_id)`` 排序；
* 分层覆盖 7 个发球阶段 + 跨 session / source，优先未使用过的 session/source。

阶段说明：本环节其实只由两个函数组成——``build_pool`` 选帧，``_to_entry`` 组行。
自动预标、数据集构建等放在本文件后半部分（同一模块，减少文件写入面）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# 同时支持两种用法：作为包导入与直接运行脚本（相对导入在两种情况下都成立）。
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path

    _PACKAGE_DIR = _Path(__file__).resolve().parent
    _VISION_DIR = _PACKAGE_DIR.parent
    _REPO_ROOT = _VISION_DIR.parent
    for _entry in (str(_REPO_ROOT), str(_VISION_DIR), str(_PACKAGE_DIR)):
        if _entry not in _sys.path:
            _sys.path.insert(0, _entry)
    __package__ = "c_perception_v2"
from .config import PATHS
from .data_prep import read_yolo_label_file

SEED = 20261013
POOL_SIZE = 80
TRAIN_SIZE = 64
VAL_SIZE = 16
PROPOSAL_CONF = 0.10

CLASS_NAMES_BR = {0: "ball", 1: "racket"}

FINETUNE_DIRNAME = "BNDSTT_BR_FINETUNE_V1"
MODEL_TAG = "ball_racket_yolov8n_v2_domain"

STAGE_ORDER: tuple[str, ...] = (
    "ready_or_hold_candidate",
    "toss_start_candidate",
    "rising_candidate",
    "mid_high_candidate",
    "apex_candidate",
    "descending_or_racket_approach_candidate",
    "contact_or_followthrough_candidate",
)

STAGE_LABELS = {
    "ready_or_hold_candidate": "发球准备",
    "toss_start_candidate": "抛球",
    "rising_candidate": "球上升",
    "mid_high_candidate": "中高位",
    "apex_candidate": "最高点附近",
    "descending_or_racket_approach_candidate": "下降/球拍接近",
    "contact_or_followthrough_candidate": "击球附近/随挥",
}


class FinetuneError(RuntimeError):
    """fine-tune 数据阶段的硬失败。"""


# ================================================================ 路径
def finetune_dir() -> Path:
    return PATHS.datasets_dir / FINETUNE_DIRNAME


def workspace_dir() -> Path:
    return finetune_dir() / "workspace"


def annotations_dir() -> Path:
    return finetune_dir() / "annotations"


def proposals_dir() -> Path:
    return finetune_dir() / "proposals"


def manifest_path() -> Path:
    return finetune_dir() / "manifest.csv"


def model_dir(tag: str | None = None) -> Path:
    return PATHS.repo_root / "artifacts" / "files" / "models" / (tag or MODEL_TAG)


def baseline_weights() -> Path:
    """本轮 fine-tune 的初始化权重：baseline v1 best.pt（只读，不覆盖）。"""
    return PATHS.model_out_dir / "best.pt"


def baseline_hash() -> str:
    path = baseline_weights()
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ================================================================ 选池
def stable_key(image_id: str, seed: int = SEED) -> str:
    return hashlib.sha256(f"{seed}:{image_id}".encode("utf-8")).hexdigest()


def _clean_row(row: dict) -> dict:
    return {
        (key or "").lstrip(chr(0xFEFF)).strip(): (value or "").strip()
        for key, value in row.items()
    }


def read_csv_rows(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [_clean_row(row) for row in csv.DictReader(handle)]


def benchmark_image_ids() -> set[str]:
    """冻结 benchmark 的 30 张 image_id（必须排除）。"""
    path = PATHS.benchmark_manifest
    if not path.is_file():
        raise FinetuneError(
            "frozen benchmark manifest missing: " + str(path) + "；先构建 BNDSTT_30_V1"
        )
    return {row["image_id"] for row in read_csv_rows(path)}


def quick_test_sessions() -> set[str]:
    path = PATHS.bndstt_mvp_dir / "split_manifest.csv"
    if not path.is_file():
        return set()
    return {
        row.get("session_id", "")
        for row in read_csv_rows(path)
        if row.get("split") == "quick_test"
    }


@dataclass
class PoolEntry:
    image_id: str
    image_path: Path
    split: str
    session_id: str
    source_id: str
    stage_hint: str
    frame_index: str
    fraction: str
    source_video_path: str
    width: str
    height: str
    has_existing_manual_gt: bool = False
    selection_reason: str = ""

    def to_row(self) -> dict:
        return {
            "image_id": self.image_id,
            "image_path": str(self.image_path),
            "split": self.split,
            "session_id": self.session_id,
            "source_id": self.source_id,
            "stage_hint": self.stage_hint,
            "stage_label": STAGE_LABELS.get(self.stage_hint, self.stage_hint),
            "frame_index": self.frame_index,
            "fraction": self.fraction,
            "source_video_path": self.source_video_path,
            "width": self.width,
            "height": self.height,
            "has_existing_manual_gt": int(self.has_existing_manual_gt),
            "annotation_source": "MODEL_PROPOSAL",
            "review_state": "UNREVIEWED",
            "selection_reason": self.selection_reason,
        }


def existing_manual_gt_ids() -> set[str]:
    """既有 42 张人工标签的 image_id（只作为参考，需重新确认）。"""
    gt_dir = PATHS.bndstt_manual_gt_dir / "annotations_json"
    if not gt_dir.is_dir():
        return set()
    return {p.stem for p in sorted(gt_dir.glob("*.json"))}


def select_pool(
    frames_rows: list[dict], mvp_dir: Path, size: int = POOL_SIZE
) -> list[PoolEntry]:
    """确定性选池：排除 benchmark 与 quick_test，按阶段轮转、优先未用 session/source。"""
    excluded = benchmark_image_ids()
    quick_sessions = quick_test_sessions()
    existing = existing_manual_gt_ids()

    candidates: list[dict] = []
    for row in frames_rows:
        image_id = row.get("image_id", "").strip()
        relative = row.get("original_image_path") or row.get("derived_gray3_path") or ""
        if not image_id and relative:
            image_id = Path(relative).stem
        if not image_id:
            continue
        if image_id in excluded:
            continue
        if row.get("session_id", "") in quick_sessions:
            continue
        if "quick_test" in str(row.get("source_video_path", "")).lower():
            continue
        row = dict(row)
        row["image_id"] = image_id
        candidates.append(row)

    grouped: dict[str, list[dict]] = {stage: [] for stage in STAGE_ORDER}
    for row in candidates:
        stage = row.get("stage_hint", "")
        if stage in grouped:
            grouped[stage].append(row)
    for stage in grouped:
        grouped[stage].sort(key=lambda row: stable_key(row.get("image_id", "")))

    chosen: list[PoolEntry] = []
    chosen_ids: set[str] = set()
    used_sessions: set[str] = set()
    used_sources: set[str] = set()

    def first_index(stage: str, predicate) -> int:
        for index, row in enumerate(grouped[stage]):
            if row.get("image_id") in chosen_ids:
                continue
            if predicate(row):
                return index
        return -1

    def take(stage: str, index: int, reason: str) -> None:
        row = grouped[stage][index]
        chosen.append(_to_entry(row, mvp_dir, existing, reason))
        chosen_ids.add(row.get("image_id", ""))
        used_sessions.add(row.get("session_id", ""))
        used_sources.add(row.get("source_id", ""))

    # 前两轮：每阶段取一帧，尽量来自未使用过的 source
    for _ in range(4):
        for stage in STAGE_ORDER:
            if len(chosen) >= size:
                break
            index = first_index(stage, lambda row: row.get("source_id") not in used_sources)
            if index >= 0:
                take(stage, index, "stage-robin-new-source")

    # 补齐：优先未使用的 session
    while len(chosen) < size:
        progressed = False
        for stage in STAGE_ORDER:
            if len(chosen) >= size:
                break
            index = first_index(stage, lambda row: row.get("session_id") not in used_sessions)
            if index < 0:
                index = first_index(stage, lambda row: True)
            if index >= 0:
                take(stage, index, "stage-robin-fill")
                progressed = True
        if not progressed:
            break
    return chosen


def _to_entry(row: dict, mvp_dir: Path, existing: set[str], reason: str) -> PoolEntry:
    relative = row.get("original_image_path") or row.get("derived_gray3_path") or ""
    image_path = Path(mvp_dir) / relative if relative else Path(mvp_dir) / "images_color"
    image_id = row.get("image_id", "").strip() or image_path.stem
    return PoolEntry(
        image_id=image_id,
        image_path=image_path,
        split=row.get("split", ""),
        session_id=row.get("session_id", ""),
        source_id=row.get("source_id", ""),
        stage_hint=row.get("stage_hint", ""),
        frame_index=row.get("frame_index", ""),
        fraction=row.get("fraction", ""),
        source_video_path=row.get("source_video_path", ""),
        width=row.get("width", "1920"),
        height=row.get("height", "1080"),
        has_existing_manual_gt=image_id in existing,
        selection_reason=(
            reason + ";benchmark-excluded;quick_test-excluded;seed=" + str(SEED)
        ),
    )


def summarize_pool(entries: list[PoolEntry]) -> dict:
    stages: dict[str, int] = {}
    for entry in entries:
        stages[entry.stage_hint] = stages.get(entry.stage_hint, 0) + 1
    missing = [e.image_id for e in entries if not e.image_path.is_file()]
    return {
        "size": len(entries),
        "sessions": len({e.session_id for e in entries}),
        "sources": len({e.source_id for e in entries}),
        "stages": stages,
        "existing_manual_gt": sum(1 for e in entries if e.has_existing_manual_gt),
        "missing_image_files": missing,
    }


def validate_pool(summary: dict, size: int = POOL_SIZE) -> list[str]:
    problems: list[str] = []
    if summary["size"] != size:
        problems.append("expected " + str(size) + " frames, got " + str(summary["size"]))
    if summary["sessions"] < 12:
        problems.append("sessions " + str(summary["sessions"]) + " < 12")
    if summary["sources"] < 20:
        problems.append("sources " + str(summary["sources"]) + " < 20")
    if len(summary["stages"]) < len(STAGE_ORDER):
        problems.append("stages covered " + str(len(summary["stages"])) + " < 7")
    if summary["missing_image_files"]:
        problems.append("missing image files: " + str(summary["missing_image_files"][:5]))
    return problems


def write_pool_manifest(
    entries: list[PoolEntry], out_dir: Path | None = None, force: bool = False
) -> Path:
    out = Path(out_dir) if out_dir is not None else finetune_dir()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "manifest.csv"
    if target.exists() and not force:
        raise FinetuneError(
            "pool manifest already exists (frozen): " + str(target)
            + "；重建需显式 force=True（会让历史结果不可比）"
        )
    columns = [
        "image_id", "image_path", "split", "session_id", "source_id", "stage_hint",
        "stage_label", "frame_index", "fraction", "source_video_path", "width", "height",
        "has_existing_manual_gt", "annotation_source", "review_state", "selection_reason",
    ]
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.to_row())
    return target


def build_pool(force: bool = False) -> dict:
    """选池 + 写 manifest + 写 report。返回摘要。"""
    frames_path = PATHS.bndstt_frames_manifest
    if not frames_path.is_file():
        raise FinetuneError("frames_manifest.csv missing: " + str(frames_path))
    frames = read_csv_rows(frames_path)
    for row in frames:
        if not row.get("image_id"):
            relative = row.get("original_image_path") or ""
            row["image_id"] = Path(relative).stem if relative else ""

    # 隔离断言
    quick_sessions = quick_test_sessions()
    frame_sessions = {row.get("session_id", "") for row in frames}
    overlap = sorted(s for s in quick_sessions & frame_sessions if s)
    if overlap:
        raise FinetuneError("quick_test sessions leaked into pool candidates: " + str(overlap))

    entries = select_pool(frames, PATHS.bndstt_mvp_dir)
    summary = summarize_pool(entries)
    problems = validate_pool(summary)
    if problems:
        raise FinetuneError("pool invalid: " + "; ".join(problems))

    target = write_pool_manifest(entries, force=force)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    excluded = benchmark_image_ids()
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED,
        "pool_size": POOL_SIZE,
        "summary": summary,
        "benchmark_excluded_count": len(excluded),
        "benchmark_leak": sorted(
            {e.image_id for e in entries} & excluded
        ),
        "quick_test_sessions": sorted(quick_sessions),
        "manifest": str(target),
        "manifest_sha256": digest,
        "image_ids": [e.image_id for e in entries],
    }
    if report["benchmark_leak"]:
        raise FinetuneError("pool leaks frozen benchmark ids: " + str(report["benchmark_leak"][:5]))
    (target.parent / "pool_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


# ================================================================ 自动预标
def prepare_workspace(force: bool = False) -> dict:
    """把 80 帧复制到 workspace，并用 baseline best.pt 生成 proposals（conf=0.10）。

    proposals **不是 GT**：``annotation_source`` 一律 ``MODEL_PROPOSAL``，
    只有人工在 UI 里确认后才变成 ``HUMAN_VERIFIED``。
    """
    import cv2

    from .ball_racket import detect_ball_racket, load_detector
    from .dataset_qa import write_image_robust

    rows = read_csv_rows(manifest_path())
    if not rows:
        raise FinetuneError("pool manifest is empty; run build_pool first")
    work = workspace_dir()
    images_out = work / "images"
    proposals_out = proposals_dir()
    images_out.mkdir(parents=True, exist_ok=True)
    proposals_out.mkdir(parents=True, exist_ok=True)

    weights = baseline_weights()
    if not weights.is_file():
        raise FinetuneError("baseline weights missing: " + str(weights))
    detector = load_detector(weights, device=0)

    proposal_counts = {"ball": 0, "racket": 0, "images_with_ball": 0, "images_with_racket": 0}
    results: list[dict] = []
    for index, row in enumerate(rows, start=1):
        src = Path(row["image_path"])
        dst = images_out / (row["image_id"] + ".jpg")
        if force or not dst.is_file():
            shutil.copy2(src, dst)
        image = cv2.imread(str(dst), cv2.IMREAD_COLOR)
        if image is None:
            # 非 ASCII 路径下 cv2.imread 不可靠：从原始路径读一次
            image = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if image is None:
            raise FinetuneError("cannot read pool image: " + str(src))
        detections, _ = detect_ball_racket(
            detector, image, conf=PROPOSAL_CONF, imgsz=640, device=0
        )
        payload = {
            "image_id": row["image_id"],
            "image_width": int(image.shape[1]),
            "image_height": int(image.shape[0]),
            "annotation_source": "MODEL_PROPOSAL",
            "is_ground_truth": False,
            "model": str(weights),
            "model_sha256": baseline_hash(),
            "conf": PROPOSAL_CONF,
            "objects": [
                {
                    "class_id": int(d.class_id),
                    "class_name": d.class_name,
                    "bbox_xyxy": [round(float(v), 3) for v in d.box.to_xyxy()],
                    "confidence": round(float(d.confidence), 6),
                }
                for d in detections
            ],
        }
        (proposals_out / (row["image_id"] + ".json")).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for det in detections:
            proposal_counts[det.class_name] = proposal_counts.get(det.class_name, 0) + 1
            if det.class_id == 0:
                proposal_counts["images_with_ball"] += 1
            elif det.class_id == 1:
                proposal_counts["images_with_racket"] += 1
        results.append(
            {
                "image_id": row["image_id"],
                "stage_hint": row["stage_hint"],
                "proposals": len(detections),
                "ball": sum(1 for d in detections if d.class_id == 0),
                "racket": sum(1 for d in detections if d.class_id == 1),
            }
        )
        if index % 10 == 0 or index == len(rows):
            print("[proposal] " + str(index) + "/" + str(len(rows)), flush=True)
        _ = write_image_robust

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_size": len(rows),
        "conf": PROPOSAL_CONF,
        "model": str(weights),
        "model_sha256": baseline_hash(),
        "proposal_counts": proposal_counts,
        "per_image": results,
        "workspace_images": str(images_out),
        "proposals": str(proposals_out),
    }
    (work / "proposal_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


# ================================================================ 人工确认读取
def load_human_annotation(image_id: str) -> dict | None:
    path = annotations_dir() / (image_id + ".json")
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("annotation_source") != "HUMAN_VERIFIED":
        return None
    return payload


def review_state_of(image_id: str) -> str:
    payload = load_human_annotation(image_id)
    return "HUMAN_VERIFIED" if payload is not None else "UNREVIEWED"


def verified_ids() -> set[str]:
    return {row["image_id"] for row in read_csv_rows(manifest_path()) if review_state_of(row["image_id"]) == "HUMAN_VERIFIED"}


def review_progress() -> dict:
    rows = read_csv_rows(manifest_path())
    verified = [row["image_id"] for row in rows if review_state_of(row["image_id"]) == "HUMAN_VERIFIED"]
    return {
        "pool_size": len(rows),
        "human_verified": len(verified),
        "remaining": len(rows) - len(verified),
        "verified_ids": verified,
    }


# ================================================================ 数据集构建
def group_key(row: dict) -> str:
    """按 session/source 分组：同一 source 不允许跨 train/val。"""
    return row["source_id"] or row["session_id"]


def assign_split(rows: list[dict], train_size: int = TRAIN_SIZE) -> dict[str, str]:
    """确定性按 source 分组拆分：先按组大小降序、再按组名，轮转填 train/val。

    保持“同一 source 不跨 split”；优先保持原始 split 的倾向（同 split 的组优先同侧）。
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)

    # 组排序：组内原始 split 多数票 → 组大小 → 组名，保证确定性
    def sort_key(item):
        key, members = item
        original = [m.get("split", "") for m in members]
        majority = max(set(original), key=original.count) if original else ""
        return (majority, -len(members), key)

    ordered = sorted(groups.items(), key=sort_key)

    assignment: dict[str, str] = {}
    train_count = 0
    val_count = 0
    for key, members in ordered:
        remaining_needed_train = train_size - train_count
        remaining_needed_val = (len(rows) - train_size) - val_count
        # 优先放 train；如果 train 已满或该组整体更适合 val，则放 val
        if remaining_needed_train >= len(members) and remaining_needed_train > 0:
            target = "train"
        elif remaining_needed_val >= len(members) and remaining_needed_val > 0:
            target = "val"
        elif remaining_needed_train >= remaining_needed_val:
            target = "train"
        else:
            target = "val"
        for member in members:
            assignment[member["image_id"]] = target
        if target == "train":
            train_count += len(members)
        else:
            val_count += len(members)
    return assignment


def build_finetune_dataset(
    out_dir: Path | None = None, require_all_verified: bool = True
) -> dict:
    """把 HUMAN_VERIFIED 的标注转成 YOLO 数据集（只含 ball/racket 两类）。"""
    rows = read_csv_rows(manifest_path())
    if not rows:
        raise FinetuneError("pool manifest is empty; run build_pool first")

    verified_rows: list[dict] = []
    skipped: list[str] = []
    for row in rows:
        payload = load_human_annotation(row["image_id"])
        if payload is None:
            skipped.append(row["image_id"])
            continue
        row = dict(row)
        row["_payload"] = payload
        verified_rows.append(row)

    if require_all_verified and skipped:
        raise FinetuneError(
            "仍有 " + str(len(skipped)) + " 张未人工确认（HUMAN_VERIFIED）："
            + str(skipped[:8]) + " ... 未确认的标注禁止进入训练"
        )
    if not verified_rows:
        raise FinetuneError("no HUMAN_VERIFIED annotations yet")

    out = Path(out_dir) if out_dir is not None else finetune_dir()
    assignment = assign_split(verified_rows, TRAIN_SIZE)

    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    image_records: list[dict] = []
    instance_counts = {"train": {"ball": 0, "racket": 0}, "val": {"ball": 0, "racket": 0}}
    for row in verified_rows:
        image_id = row["image_id"]
        split = assignment[image_id]
        payload = row["_payload"]
        width = int(payload["image_width"])
        height = int(payload["image_height"])
        source_image = workspace_dir() / "images" / (image_id + ".jpg")
        if not source_image.is_file():
            source_image = Path(row["image_path"])
        target_image = out / "images" / split / (image_id + ".jpg")
        if not target_image.is_file():
            shutil.copy2(source_image, target_image)

        lines: list[str] = []
        for obj in payload.get("objects", []):
            class_id = int(obj["class_id"])
            if class_id not in CLASS_NAMES_BR:
                continue  # hand 等旧类别一律丢弃
            x1, y1, x2, y2 = (float(v) for v in obj["bbox_xyxy"])
            x1, y1 = max(0.0, x1), max(0.0, y1)
            x2, y2 = min(float(width), x2), min(float(height), y2)
            if x2 - x1 <= 0 or y2 - y1 <= 0:
                continue
            cx = (x1 + x2) / 2.0 / width
            cy = (y1 + y2) / 2.0 / height
            bw = (x2 - x1) / width
            bh = (y2 - y1) / height
            lines.append(
                str(class_id) + " " + f"{cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"
            )
            instance_counts[split][CLASS_NAMES_BR[class_id]] += 1
        (out / "labels" / split / (image_id + ".txt")).write_text(
            (chr(10).join(lines) + chr(10)) if lines else "", encoding="utf-8"
        )
        image_records.append(
            {"image_id": image_id, "split": split, "instances": len(lines)}
        )

    import yaml

    yaml_path = out / "data.yaml"
    yaml_path.write_text(
        "# 自动生成：BNDSTT 域内 fine-tune 数据集（只含 HUMAN_VERIFIED 标注）" + chr(10)
        + "# 不要手工编辑：由 vision/c_perception_v2/finetune_domain.py 重新生成。" + chr(10)
        + yaml.safe_dump(
            {
                "path": out.resolve().as_posix(),
                "train": "images/train",
                "val": "images/val",
                "nc": 2,
                "names": {0: "ball", 1: "racket"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # 泄漏自检：同一 source 不得跨 split
    by_source: dict[str, set[str]] = {}
    for row in verified_rows:
        by_source.setdefault(group_key(row), set()).add(assignment[row["image_id"]])
    leaky = {key: sorted(v) for key, v in by_source.items() if len(v) > 1}

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verified_images": len(verified_rows),
        "assignment": assignment,
        "train_images": sum(1 for v in assignment.values() if v == "train"),
        "val_images": sum(1 for v in assignment.values() if v == "val"),
        "instances": instance_counts,
        "source_split_leak": leaky,
        "dataset_dir": str(out),
        "data_yaml": str(yaml_path),
        "per_image": image_records,
    }
    if leaky:
        raise FinetuneError("source split leak detected: " + str(list(leaky)[:5]))
    (out / "dataset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def dataset_hash() -> str:
    """数据集内容哈希：对所有 images/labels 文件名+内容做 sha256。"""
    base = finetune_dir()
    digest = hashlib.sha256()
    for split in ("train", "val"):
        for kind in ("images", "labels"):
            folder = base / kind / split
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    digest.update(split.encode())
                    digest.update(kind.encode())
                    digest.update(path.name.encode())
                    digest.update(path.read_bytes())
    return digest.hexdigest()


def cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BNDSTT 域内 fine-tune V1 数据流程")
    parser.add_argument(
        "command",
        choices=["pool", "proposals", "status", "build"],
        help="pool=选池并冻结 manifest; proposals=复制+best.pt预标; status=人工确认进度; build=构建数据集",
    )
    parser.add_argument("--force", action="store_true", help="允许覆盖已冻结的 manifest")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="build 时允许未全部确认（仅用于调试，正式训练禁止）",
    )
    args = parser.parse_args(argv)

    if args.command == "pool":
        report = build_pool(force=args.force)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.command == "proposals":
        report = prepare_workspace(force=args.force)
        print(json.dumps({k: v for k, v in report.items() if k != "per_image"},
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(review_progress(), ensure_ascii=False, indent=2))
        return 0
    report = build_finetune_dataset(require_all_verified=not args.allow_partial)
    print(json.dumps({k: v for k, v in report.items() if k not in ("per_image", "assignment")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(cli())
