"""fine-tune 阶段的评估与阈值扫描（第 12/13/15/16/17 条要求）。

包含四件事
----------
1. :func:`bndstt_frame_metrics`：在固定 ``BNDSTT_30_V1`` 上统计
   ``ball / racket / both`` 的**帧级检出数**与误检数（可与 baseline 公平对比）；
2. :func:`scan_conf_thresholds`：对一批 conf 值扫描帧级召回与误检，给实时系统挑阈值；
3. :func:`public_test_metrics`：公开 test split 指标，额外给 duplicate-excluded 版本；
4. :func:`review_out_of_bounds`：复核原始 out-of-bounds 框，区分 clip 与 drop。

注意：本模块**不修改**原始数据、不修改 frozen benchmark、不使用 quick_test。
"""

from __future__ import annotations

import csv
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
from .config import INFER_IMGSZ, INFER_IOU, PATHS
from .finetune_domain import read_csv_rows
from .yolo_io import Box, box_iou, yolo_norm_to_pixel

CONF_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
DEFAULT_CONF = 0.15
DUPLICATE_HASHES: dict[str, list[dict]] = {}


# ================================================================ 通用预测
def predict_boxes(model, image, conf: float, imgsz: int = INFER_IMGSZ, iou: float = INFER_IOU,
                   device: str | int = 0) -> list[Box]:
    """跑一次推理，返回原图坐标的 xyxy 框（class_id 保留）。"""
    results = model.predict(image, conf=float(conf), iou=float(iou), imgsz=int(imgsz),
                            device=device, verbose=False)
    boxes: list[Box] = []
    for result in results:
        raw = getattr(result, "boxes", None)
        if raw is None or len(raw) == 0:
            continue
        for xyxy, confidence, class_id in zip(raw.xyxy.tolist(), raw.conf.tolist(), raw.cls.tolist()):
            boxes.append(
                Box(
                    float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]),
                    class_id=int(class_id), confidence=float(confidence),
                )
            )
    boxes.sort(key=lambda b: -b.confidence)
    return boxes


# ================================================================ BNDSTT_30 帧级指标
def load_benchmark_rows() -> list[dict]:
    path = PATHS.benchmark_manifest
    if not path.is_file():
        raise FileNotFoundError("frozen benchmark manifest missing: " + str(path))
    return read_csv_rows(path)


def bndstt_frame_metrics(
    weights: str | Path,
    conf: float = DEFAULT_CONF,
    imgsz: int = INFER_IMGSZ,
    device: str | int = 0,
    class_ids: tuple[int, ...] = (0, 1),
) -> dict:
    """在固定 30 帧上统计帧级检出：ball / racket / both，以及每类实例数与重复框。

    ``class_ids`` 允许只看一部分类别（例如 ball-only 扫描）。
    """
    from ultralytics import YOLO

    from .dataset_qa import read_image_robust

    weights = Path(weights)
    if not weights.is_file():
        raise FileNotFoundError("weights not found: " + str(weights))
    rows = load_benchmark_rows()
    model = YOLO(str(weights))

    frames: list[dict] = []
    for row in rows:
        image_path = Path(row["image_path"])
        image = read_image_robust(image_path)
        if image is None:
            raise ValueError("cannot read benchmark image: " + str(image_path))
        boxes = [b for b in predict_boxes(model, image, conf, imgsz, device=device)
                 if b.class_id in class_ids]
        balls = [b for b in boxes if b.class_id == 0]
        rackets = [b for b in boxes if b.class_id == 1]
        frames.append(
            {
                "image_id": row["image_id"],
                "stage_hint": row.get("stage_hint", ""),
                "ball_count": len(balls),
                "racket_count": len(rackets),
                "ball_conf_max": max((b.confidence for b in balls), default=None),
                "racket_conf_max": max((b.confidence for b in rackets), default=None),
                "ball_boxes": [round(float(v), 1) for b in balls for v in b.to_xyxy()][:40],
            }
        )

    ball_frames = sum(1 for f in frames if f["ball_count"] > 0)
    racket_frames = sum(1 for f in frames if f["racket_count"] > 0)
    both_frames = sum(1 for f in frames if f["ball_count"] > 0 and f["racket_count"] > 0)
    ball_instances = sum(f["ball_count"] for f in frames)
    racket_instances = sum(f["racket_count"] for f in frames)
    total = len(frames)
    return {
        "weights": str(weights),
        "conf": float(conf),
        "imgsz": int(imgsz),
        "frames": total,
        "ball_detected_frames": ball_frames,
        "racket_detected_frames": racket_frames,
        "both_detected_frames": both_frames,
        "ball_frame_recall": round(ball_frames / total, 4) if total else None,
        "racket_frame_recall": round(racket_frames / total, 4) if total else None,
        "both_frame_recall": round(both_frames / total, 4) if total else None,
        "ball_instances": ball_instances,
        "racket_instances": racket_instances,
        "ball_extra_boxes": ball_instances - ball_frames,
        "racket_extra_boxes": racket_instances - racket_frames,
        "per_frame": frames,
    }


def scan_conf_thresholds(
    weights: str | Path,
    confs: tuple[float, ...] = CONF_GRID,
    imgsz: int = INFER_IMGSZ,
    device: str | int = 0,
) -> dict:
    """对每个 conf 扫描 BNDSTT_30 帧级召回与多余框（实时系统阈值选择依据）。"""
    table: list[dict] = []
    for conf in confs:
        metrics = bndstt_frame_metrics(weights, conf=conf, imgsz=imgsz, device=device)
        table.append(
            {
                "conf": conf,
                "ball_frames": metrics["ball_detected_frames"],
                "racket_frames": metrics["racket_detected_frames"],
                "both_frames": metrics["both_detected_frames"],
                "ball_extra_boxes": metrics["ball_extra_boxes"],
                "racket_extra_boxes": metrics["racket_extra_boxes"],
                "ball_frame_recall": metrics["ball_frame_recall"],
                "racket_frame_recall": metrics["racket_frame_recall"],
            }
        )
    # 推荐阈值：在满足 ball 召回最大化的前提下，取误检最少（最小 conf 中召回已饱和者优先低预算）
    best_recall = max(row["ball_frames"] for row in table) if table else 0
    candidates = [row for row in table if row["ball_frames"] == best_recall]
    recommended = max(candidates, key=lambda row: row["conf"]) if candidates else None
    return {
        "weights": str(weights),
        "confs": list(confs),
        "table": table,
        "recommended_conf": recommended["conf"] if recommended else None,
        "recommendation_rule": (
            "在 ball 帧召回达到最大的前提下取最大的 conf（更高阈值=更少误检），"
            "同时参考 racket 帧召回不下降"
        ),
    }


# ================================================================ 公开 test + duplicate
def duplicate_groups() -> list[list[dict]]:
    """公开 BR 数据集中的重复图组（同 sha256）。"""
    manifest = PATHS.br_dir / "manifest.csv"
    if not manifest.is_file():
        return []
    rows = read_csv_rows(manifest)
    by_hash: dict[str, list[dict]] = {}
    for row in rows:
        by_hash.setdefault(row["sha256"], []).append(row)
    return [group for group in by_hash.values() if len(group) > 1]


def build_duplicate_excluded_test(out_dir: Path | None = None) -> dict:
    """构造 duplicate-excluded 的 test 数据集（仅复制未被排除的图片，原始数据不动）。"""
    groups = duplicate_groups()
    if not groups:
        return {"excluded": [], "out_dir": None, "note": "no duplicates found"}
    excluded: list[dict] = []
    for group in groups:
        # 保留排序第一个，其余（含跨 split 的那份）排除；若组内跨 split，两个都排除一份
        ordered = sorted(group, key=lambda r: (r["split"], r["image"]))
        for row in ordered[1:]:
            excluded.append(row)
        # 若同组跨 split，train 侧也一并排除以彻底消除泄漏
        splits = {row["split"] for row in group}
        if len(splits) > 1:
            for row in ordered:
                if row["split"] != "test":
                    excluded.append(row)

    seen: set[str] = set()
    unique_excluded = []
    for row in excluded:
        key = row["split"] + "/" + row["image"]
        if key not in seen:
            seen.add(key)
            unique_excluded.append(row)

    out = Path(out_dir) if out_dir is not None else PATHS.reports_dir / "duplicate_excluded_test"
    if (out / "images" / "test").exists():
        shutil.rmtree(out)
    (out / "images" / "test").mkdir(parents=True, exist_ok=True)
    (out / "labels" / "test").mkdir(parents=True, exist_ok=True)
    excluded_names = {Path(r["image"]).name for r in unique_excluded if r["split"] == "test"}

    copied = 0
    for row in read_csv_rows(PATHS.br_dir / "manifest.csv"):
        if row["split"] != "test":
            continue
        name = Path(row["image"]).name
        if name in excluded_names:
            continue
        shutil.copy2(PATHS.br_dir / row["image"], out / "images" / "test" / name)
        label_src = PATHS.br_dir / row["label"]
        if label_src.is_file():
            shutil.copy2(label_src, out / "labels" / "test" / label_src.name)
        copied += 1

    import yaml

    data_yaml = out / "data.yaml"
    data_yaml.write_text(
        "# duplicate-excluded 公开 test（只用于报告泄漏争议，不用于训练）" + chr(10)
        + yaml.safe_dump(
            {
                "path": out.resolve().as_posix(),
                "train": "images/test",
                "val": "images/test",
                "test": "images/test",
                "nc": 2,
                "names": {0: "ball", 1: "racket"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return {
        "out_dir": str(out),
        "data_yaml": str(data_yaml),
        "duplicate_groups": len(groups),
        "excluded_rows": unique_excluded,
        "excluded_test_images": sorted(excluded_names),
        "test_images_after_exclusion": copied,
    }


def metrics_from_object(metrics) -> dict:
    """从 Ultralytics DetMetrics 读取 overall 与 per-class 指标。"""
    box = getattr(metrics, "box", None)
    if box is None:
        return {"overall": {}, "per_class": {}}

    def as_list(value):
        if value is None:
            return []
        try:
            return [float(v) for v in value]
        except TypeError:
            return [float(value)]

    def scalar(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    names = getattr(metrics, "names", {}) or {}
    if isinstance(names, (list, tuple)):
        names = dict(enumerate(names))
    precision, recall = as_list(getattr(box, "p", None)), as_list(getattr(box, "r", None))
    ap50, ap = as_list(getattr(box, "ap50", None)), as_list(getattr(box, "ap", None))
    per_class = {}
    for index in sorted(int(k) for k in names):
        per_class[str(names[index])] = {
            "class_id": index,
            "precision": precision[index] if index < len(precision) else None,
            "recall": recall[index] if index < len(recall) else None,
            "ap50": ap50[index] if index < len(ap50) else None,
            "ap50_95": ap[index] if index < len(ap) else None,
        }
    return {
        "overall": {
            "precision": scalar(getattr(box, "mp", None)),
            "recall": scalar(getattr(box, "mr", None)),
            "map50": scalar(getattr(box, "map50", None)),
            "map50_95": scalar(getattr(box, "map", None)),
        },
        "per_class": per_class,
    }


def public_test_metrics(
    weights: str | Path,
    data_yaml: Path | None = None,
    split: str = "test",
    imgsz: int = INFER_IMGSZ,
    device: str | int = 0,
) -> dict:
    """在公开 test split 上评估（可指定 duplicate-excluded 的 data.yaml）。"""
    from ultralytics import YOLO

    weights = Path(weights)
    data_yaml = Path(data_yaml) if data_yaml else PATHS.br_data_yaml
    model = YOLO(str(weights))
    metrics = model.val(
        data=str(data_yaml.resolve()), split=split, imgsz=int(imgsz), device=device,
        plots=False, workers=0, verbose=False, project=str(PATHS.project_dir.parent),
        name="val_tmp_" + weights.parent.name, exist_ok=True,
    )
    parsed = metrics_from_object(metrics)
    parsed["weights"] = str(weights)
    parsed["data_yaml"] = str(data_yaml)
    parsed["speed_ms_per_image"] = getattr(metrics, "speed", {})
    return parsed


# ================================================================ out-of-bounds 复核
def review_out_of_bounds(raw_data_yaml: Path | None = None) -> dict:
    """复核原始标签里的 out-of-bounds 框：轻微越界则 clip，明显错误则 drop。

    只做**审计记录**，不修改原始数据、不重训 baseline。
    """
    raw_yaml = Path(raw_data_yaml) if raw_data_yaml else PATHS.raw_dir / "data.yaml"
    if not raw_yaml.is_file():
        return {"available": False, "note": "raw dataset not present: " + str(raw_yaml)}

    import yaml

    from .data_prep import normalize_names, resolve_label_dir, resolve_split_dir

    payload = yaml.safe_load(raw_yaml.read_text(encoding="utf-8"))
    names = normalize_names(payload.get("names"))
    root = raw_yaml.parent

    from PIL import Image

    clip_tolerance = 0.02  # 越界不超过画幅 2% 视为轻微，clip 保留
    records: list[dict] = []
    counts = {"clip": 0, "drop": 0}
    for split in ("train", "valid", "test"):
        image_dir = resolve_split_dir(root, split)
        label_dir = resolve_label_dir(root, split)
        if image_dir is None or label_dir is None:
            continue
        for label_path in sorted(label_dir.glob("*.txt")):
            image_path = None
            for suffix in (".jpg", ".jpeg", ".png"):
                candidate = image_dir / (label_path.stem + suffix)
                if candidate.is_file():
                    image_path = candidate
                    break
            if image_path is None:
                continue
            with Image.open(image_path) as handle:
                width, height = handle.size
            for line_number, line in enumerate(
                label_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                parts = line.split()
                if len(parts) != 5:
                    continue
                class_id = int(float(parts[0]))
                cx, cy, w, h = (float(v) for v in parts[1:])
                box = yolo_norm_to_pixel(class_id, cx, cy, w, h, width, height)
                if box.is_inside(width, height):
                    continue
                overshoot = max(
                    0.0,
                    -box.x1 / width, -box.y1 / height,
                    (box.x2 - width) / width, (box.y2 - height) / height,
                )
                action = "clip" if overshoot <= clip_tolerance else "drop"
                counts[action] += 1
                records.append(
                    {
                        "split": split,
                        "label": label_path.name,
                        "line": line_number,
                        "class_name": names.get(class_id, str(class_id)),
                        "bbox_xyxy": [round(v, 2) for v in box.to_xyxy()],
                        "image_size": [width, height],
                        "overshoot_ratio": round(overshoot, 6),
                        "action": action,
                    }
                )

    target = PATHS.reports_dir / "out_of_bounds_review.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    columns = ["split", "label", "line", "class_name", "bbox_xyxy", "image_size",
               "overshoot_ratio", "action"]
    with open(target, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["bbox_xyxy"] = ";".join(str(v) for v in record["bbox_xyxy"])
            row["image_size"] = "x".join(str(v) for v in record["image_size"])
            writer.writerow(row)
    return {
        "available": True,
        "clip_tolerance": clip_tolerance,
        "clipped": counts["clip"],
        "dropped": counts["drop"],
        "total_oob": len(records),
        "csv": str(target),
        "note": (
            "仅审计记录：轻微越界（<=2% 画幅）建议 clip，明显错误建议 drop。"
            "本轮不修改原始数据、不重训 baseline。"
        ),
        "records": records,
    }
