"""Stage 6 入口：在 v2 test split 上做正式评估 + tiny-ball 专项分析（S/T/AK）。

* 指标全部来自 Ultralytics 自己的 validator（不手填、不估）；
* 分别报告 overall / ball / racket 的 P、R、AP50、AP50-95；
* 生成 test_ball_failures/：FN 候选、低置信 ball、明显误检、小球样例与 contact sheet；
* 输出 ball bbox 像素尺寸分布，并与 BNDSTT 域内球尺寸对比，量化 domain gap。

注意：公开页面的 87.4% / 92.0% / 85.6% 是 Roboflow 页面指标，不是本项目指标（AJ）。
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 同时支持两种用法：作为包导入（vision.c_perception_v2.xxx）与直接运行脚本。
# 直接运行时先把 仓库根/vision/包目录 放进 sys.path，再走绝对导入，
# 不替换 sys.modules、不改 __name__，因此文件末尾的 __main__ 守卫照常生效。
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

from . import CLASS_BALL, CLASS_NAMES, CLASS_RACKET  # noqa: E402,F401
from .config import (  # noqa: E402
    INFER_CONF_REPORT,
    INFER_IMGSZ,
    INFER_IOU,
    PATHS,
)
from .dataset_qa import (  # noqa: E402
    collect_ball_sizes,
    contact_sheet,
    write_image_robust,
    load_split_samples,
    read_image_robust,
    read_label_boxes,
)
from .yolo_io import (  # noqa: E402
    COLOR_BALL,
    COLOR_RACKET,
    Box,
    box_iou,
    draw_box,
    draw_label,
    draw_legend,
)

MATCH_IOU = 0.30
LOW_CONF_THRESHOLD = 0.25
SMALL_BALL_QUANTILE = 0.25
FAILURE_PANEL_WIDTH = 640


def metrics_from_object(metrics, names: dict | None = None) -> dict:
    """直接从 Ultralytics ``DetMetrics`` 对象读取指标。

    8.2.82 的 ``val()`` 默认不写 metrics JSON，因此以内存对象为准：
    ``metrics.box.p / r / ap50 / ap`` 是 per-class 数组，``mp/mr/map50/map`` 是总体。
    """
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

    class_names = names or getattr(metrics, "names", {}) or {}
    if isinstance(class_names, (list, tuple)):
        class_names = dict(enumerate(class_names))

    precision = as_list(getattr(box, "p", None))
    recall = as_list(getattr(box, "r", None))
    ap50 = as_list(getattr(box, "ap50", None))
    ap = as_list(getattr(box, "ap", None))

    per_class: dict[str, dict] = {}
    for index in sorted(int(k) for k in class_names):
        per_class[str(class_names[index])] = {
            "class_id": index,
            "precision": precision[index] if index < len(precision) else None,
            "recall": recall[index] if index < len(recall) else None,
            "ap50": ap50[index] if index < len(ap50) else None,
            "ap50_95": ap[index] if index < len(ap) else None,
        }

    overall = {
        "precision": _scalar(getattr(box, "mp", None)),
        "recall": _scalar(getattr(box, "mr", None)),
        "map50": _scalar(getattr(box, "map50", None)),
        "map50_95": _scalar(getattr(box, "map", None)),
    }
    if overall["precision"] is None and precision:
        overall["precision"] = sum(precision) / len(precision)
    if overall["recall"] is None and recall:
        overall["recall"] = sum(recall) / len(recall)
    return {"overall": overall, "per_class": per_class}


def _scalar(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_test_metrics(metrics_json: Path) -> dict:
    """从 Results 写出的 metrics JSON 中读取 overall 与 per-class 指标。"""
    payload = json.loads(Path(metrics_json).read_text(encoding="utf-8"))
    overall = {
        "precision": payload.get("metrics/precision(B)"),
        "recall": payload.get("metrics/recall(B)"),
        "map50": payload.get("metrics/mAP50(B)"),
        "map50_95": payload.get("metrics/mAP50-95(B)"),
    }
    per_class: dict[str, dict] = {}
    results_dict = payload.get("results_dict") or {}
    skip = {"precision", "recall", "map50", "map50-95"}
    for name, values in results_dict.items():
        cleaned = str(name).strip()
        if cleaned.lower() in skip or not isinstance(values, dict):
            continue
        per_class[cleaned] = {
            "class_id": None,
            "precision": values.get("precision"),
            "recall": values.get("recall"),
            "ap50": values.get("map50"),
            "ap50_95": values.get("map50-95"),
        }
    for class_id, name in enumerate(payload.get("class_names") or []):
        entry = per_class.setdefault(
            str(name),
            {"class_id": class_id, "precision": None, "recall": None, "ap50": None, "ap50_95": None},
        )
        entry["class_id"] = class_id
    return {"overall": overall, "per_class": per_class, "raw_keys": sorted(payload.keys())}


def read_training_progress(results_csv: Path) -> dict:
    """best epoch / 实际跑完的 epoch。"""
    path = Path(results_csv)
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            {(k or "").strip(): v for k, v in row.items()} for row in csv.DictReader(handle)
        ]
    if not rows:
        return {}
    map_key = next((k for k in rows[0] if "mAP50-95" in k and k.startswith("metrics")), None)
    if map_key is None:
        return {"epochs_run": len(rows)}
    best = max(rows, key=lambda row: float(row.get(map_key) or 0.0))
    return {
        "epochs_run": len(rows),
        "best_epoch": int(float(best.get("epoch", 0))),
        "best_map50_95": float(best.get(map_key) or 0.0),
        "last_map50_95": float(rows[-1].get(map_key) or 0.0),
    }


def read_args_yaml(run_dir: Path) -> dict:
    import yaml

    path = Path(run_dir) / "args.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _predict(model, image, conf: float, imgsz: int, device, iou: float = INFER_IOU):
    results = model.predict(image, conf=conf, iou=iou, imgsz=imgsz, device=device, verbose=False)
    names = model.names if isinstance(model.names, dict) else dict(enumerate(model.names))
    detections: list[Box] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            continue
        for xyxy, confidence, class_id in zip(
            boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()
        ):
            detections.append(
                Box(
                    float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]),
                    class_id=int(class_id), confidence=float(confidence),
                )
            )
    detections.sort(key=lambda b: -b.confidence)
    return detections, {int(k): str(v) for k, v in names.items()}


def _panel(image, title: str, gt_boxes: list[Box], preds: list[Box]):
    """GT 实线 + 预测虚线，便于判断“YOLO 错还是标签怪”。"""
    canvas = image.copy()
    for box in gt_boxes:
        color = COLOR_BALL if box.class_id == CLASS_BALL else COLOR_RACKET
        draw_box(canvas, box, label="GT " + CLASS_NAMES[box.class_id], color=color, thickness=2)
    for box in preds:
        color = COLOR_BALL if box.class_id == CLASS_BALL else COLOR_RACKET
        draw_box(
            canvas, box,
            label="P " + CLASS_NAMES[box.class_id] + " " + format(box.confidence, ".2f"),
            color=color, thickness=2, dashed=True,
        )
    draw_legend(
        canvas,
        [
            ("ball GT x" + str(sum(1 for b in gt_boxes if b.class_id == CLASS_BALL)), COLOR_BALL),
            ("racket GT x" + str(sum(1 for b in gt_boxes if b.class_id == CLASS_RACKET)), COLOR_RACKET),
            ("ball pred x" + str(sum(1 for b in preds if b.class_id == CLASS_BALL)), COLOR_BALL),
            ("racket pred x" + str(sum(1 for b in preds if b.class_id == CLASS_RACKET)), COLOR_RACKET),
        ],
    )
    draw_label(canvas, title, (8, canvas.shape[0] - 26), (55, 55, 55), scale=0.5)
    return canvas


def analyze_test_split(
    weights: Path,
    data_yaml: Path | None = None,
    out_dir: Path | None = None,
    device: str | int = 0,
    imgsz: int = INFER_IMGSZ,
    conf: float = INFER_CONF_REPORT,
    max_panels: int = 60,
) -> dict:
    """ball 专项失败分析：FN 候选 / 低置信 / 误检 / 小球。"""
    import cv2
    from ultralytics import YOLO

    _ = data_yaml
    samples = load_split_samples(PATHS.br_dir, "test")
    if not samples:
        raise FileNotFoundError("no test samples under " + str(PATHS.br_dir / "images" / "test"))

    ball_sizes = []
    for sample in samples:
        boxes, _ = read_label_boxes(sample)
        for box in boxes:
            if box.class_id == CLASS_BALL:
                ball_sizes.append(box.width)
    ball_sizes.sort()
    small_threshold = (
        ball_sizes[int(round(SMALL_BALL_QUANTILE * (len(ball_sizes) - 1)))] if ball_sizes else 0.0
    )

    model = YOLO(str(weights))
    out = Path(out_dir) if out_dir is not None else PATHS.failures_dir
    out.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    fn_panels, low_panels, fp_panels, small_panels, miss_panels = [], [], [], [], []
    ball_gt_total = ball_matched_total = racket_gt_total = racket_matched_total = 0

    for sample in samples:
        image = read_image_robust(sample.image_path)
        if image is None:
            continue
        gt_boxes, _ = read_label_boxes(sample)
        preds, _ = _predict(model, image, conf=conf, imgsz=imgsz, device=device)
        gt_balls = [b for b in gt_boxes if b.class_id == CLASS_BALL]
        gt_rackets = [b for b in gt_boxes if b.class_id == CLASS_RACKET]
        pred_balls = [b for b in preds if b.class_id == CLASS_BALL]
        pred_rackets = [b for b in preds if b.class_id == CLASS_RACKET]

        unmatched_gt_balls = list(gt_balls)
        unmatched_pred_balls = list(pred_balls)
        ball_matches: list[float] = []
        for gt in list(unmatched_gt_balls):
            best, best_iou = None, 0.0
            for pred in unmatched_pred_balls:
                iou = box_iou(gt, pred)
                if iou > best_iou:
                    best, best_iou = pred, iou
            if best is not None and best_iou >= MATCH_IOU:
                unmatched_gt_balls.remove(gt)
                unmatched_pred_balls.remove(best)
                ball_matches.append(best_iou)

        unmatched_gt_rackets = list(gt_rackets)
        unmatched_pred_rackets = list(pred_rackets)
        for gt in list(unmatched_gt_rackets):
            best, best_iou = None, 0.0
            for pred in unmatched_pred_rackets:
                iou = box_iou(gt, pred)
                if iou > best_iou:
                    best, best_iou = pred, iou
            if best is not None and best_iou >= MATCH_IOU:
                unmatched_gt_rackets.remove(gt)
                unmatched_pred_rackets.remove(best)

        ball_gt_total += len(gt_balls)
        ball_matched_total += len(ball_matches)
        racket_gt_total += len(gt_rackets)
        racket_matched_total += len(gt_rackets) - len(unmatched_gt_rackets)

        worst_iou = min(ball_matches) if len(ball_matches) == len(gt_balls) and ball_matches else 0.0
        records.append(
            {
                "image": sample.image_path.name,
                "width": sample.image_width,
                "height": sample.image_height,
                "ball_gt": len(gt_balls),
                "ball_pred": len(pred_balls),
                "ball_fn": len(unmatched_gt_balls),
                "ball_fp": len(unmatched_pred_balls),
                "racket_gt": len(gt_rackets),
                "racket_pred": len(pred_rackets),
                "racket_fn": len(unmatched_gt_rackets),
                "racket_fp": len(unmatched_pred_rackets),
                "ball_min_matched_iou": round(worst_iou, 4),
                "ball_gt_width_px": ";".join(format(b.width, ".1f") for b in gt_balls),
            }
        )

        title = (
            sample.image_path.name + " | ball GT" + str(len(gt_balls))
            + "/P" + str(len(pred_balls))
            + " FN" + str(len(unmatched_gt_balls))
            + " FP" + str(len(unmatched_pred_balls))
        )
        panel = _panel(image, title, gt_boxes, preds)
        if unmatched_gt_balls and len(fn_panels) < max_panels:
            fn_panels.append(panel)
        if unmatched_pred_balls and len(fp_panels) < max_panels:
            fp_panels.append(panel)
        low_conf = [b for b in pred_balls if b.confidence < LOW_CONF_THRESHOLD]
        if low_conf and len(low_panels) < max_panels:
            low_panels.append(panel)
        if gt_balls and all(b.width <= small_threshold for b in gt_balls):
            if len(small_panels) < max_panels:
                small_panels.append(panel)
        if gt_balls and not pred_balls and len(miss_panels) < max_panels:
            miss_panels.append(panel)

    columns = [
        "image", "width", "height", "ball_gt", "ball_pred", "ball_fn", "ball_fp",
        "racket_gt", "racket_pred", "racket_fn", "racket_fp",
        "ball_min_matched_iou", "ball_gt_width_px",
    ]
    with open(out / "test_failures.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    written: dict[str, str] = {}
    for name, panels in (
        ("test_ball_fn_contact_sheet.jpg", fn_panels),
        ("test_ball_fp_contact_sheet.jpg", fp_panels),
        ("test_ball_low_conf_contact_sheet.jpg", low_panels),
        ("test_ball_small_contact_sheet.jpg", small_panels),
        ("test_ball_missing_contact_sheet.jpg", miss_panels),
    ):
        if panels:
            sheet = contact_sheet(panels, columns=4, panel_width=FAILURE_PANEL_WIDTH)
            write_image_robust(str(out / name), sheet, jpeg_quality=86)
            written[name] = str(out / name)

    summary = {
        "weights": str(weights),
        "conf": conf,
        "match_iou": MATCH_IOU,
        "test_images": len(records),
        "ball_gt_instances": ball_gt_total,
        "ball_matched_instances": ball_matched_total,
        "ball_missed_instances": ball_gt_total - ball_matched_total,
        "ball_match_rate": round(ball_matched_total / ball_gt_total, 4) if ball_gt_total else None,
        "racket_gt_instances": racket_gt_total,
        "racket_matched_instances": racket_matched_total,
        "racket_match_rate": round(racket_matched_total / racket_gt_total, 4)
        if racket_gt_total
        else None,
        "images_with_ball_fn": sum(1 for r in records if r["ball_fn"] > 0),
        "images_with_ball_fp": sum(1 for r in records if r["ball_fp"] > 0),
        "images_with_no_ball_pred": sum(
            1 for r in records if r["ball_gt"] > 0 and r["ball_pred"] == 0
        ),
        "small_ball_threshold_px": round(small_threshold, 2),
        "contact_sheets": written,
        "failures_csv": str(out / "test_failures.csv"),
    }
    (out / "test_failures_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def bndstt_ball_sizes(limit: int | None = None) -> dict:
    """BNDSTT 人工 GT 中 ball 的像素尺寸，用于 domain gap 对比。

    这些是**域内少量人工标签**，只用于尺寸对比，绝不进入公开数据训练。
    """
    gt_dir = PATHS.bndstt_manual_gt_dir / "annotations_json"
    if not gt_dir.is_dir():
        return {"available": False, "note": "BNDSTT_MANUAL_GT_V1/annotations_json missing"}
    widths: list[float] = []
    heights: list[float] = []
    files = sorted(gt_dir.glob("*.json"))
    if limit:
        files = files[:limit]
    balls = rackets = hands = 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for obj in payload.get("objects", []):
            name = str(obj.get("class_name", "")).lower()
            bbox = obj.get("bbox_xyxy") or [0, 0, 0, 0]
            width = float(bbox[2]) - float(bbox[0])
            height = float(bbox[3]) - float(bbox[1])
            if name == "ball":
                balls += 1
                widths.append(width)
                heights.append(height)
            elif name == "racket":
                rackets += 1
            elif name == "hand":
                hands += 1
    if not widths:
        return {"available": False, "annotated_images": len(files)}
    widths.sort()
    heights.sort()

    def percentile(values: list[float], fraction: float) -> float:
        index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
        return round(values[index], 2)

    return {
        "available": True,
        "annotated_images": len(files),
        "ball_instances": balls,
        "racket_instances": rackets,
        "hand_instances_legacy": hands,
        "ball_width_px": {
            "min": round(widths[0], 2),
            "median": percentile(widths, 0.5),
            "max": round(widths[-1], 2),
        },
        "ball_height_px": {
            "min": round(heights[0], 2),
            "median": percentile(heights, 0.5),
            "max": round(heights[-1], 2),
        },
        "note": (
            "BNDSTT 人工 ball 框包含运动模糊/拖影，明显大于球的清晰像元尺寸；"
            "跨域对比时应按此说明解读。旧 hand 标签保留历史，本轮不参与任何训练。"
        ),
    }


def run_eval(
    weights: Path | None = None,
    data_yaml: Path | None = None,
    device: str | int = 0,
    imgsz: int = INFER_IMGSZ,
    split: str = "test",
    analyze: bool = True,
) -> dict:
    from ultralytics import YOLO

    weights = Path(weights) if weights else PATHS.model_out_dir / "best.pt"
    if not weights.is_file():
        raise FileNotFoundError("weights not found: " + str(weights))
    data_yaml = Path(data_yaml) if data_yaml else PATHS.br_data_yaml

    model = YOLO(str(weights))
    metrics = model.val(
        data=str(data_yaml.resolve()),
        split=split,
        imgsz=int(imgsz),
        device=device,
        plots=True,
        project=str(PATHS.project_dir.parent),
        name=PATHS.project_dir.name + "_eval_" + split,
        exist_ok=True,
        verbose=True,
    )

    save_dir = Path(getattr(metrics, "save_dir", PATHS.project_dir.parent))
    metrics_json = None
    for candidate in sorted(save_dir.glob("*.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if payload:
            metrics_json = candidate
            break
    parsed = metrics_from_object(metrics, getattr(metrics, "names", None))
    if not parsed.get("overall"):
        # 兜底：万一某个版本把指标写进了 JSON
        parsed = read_test_metrics(metrics_json) if metrics_json else {"overall": {}, "per_class": {}}

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weights": str(weights),
        "data_yaml": str(data_yaml),
        "split": split,
        "imgsz": imgsz,
        "val_dir": str(save_dir),
        "metrics_json": str(metrics_json) if metrics_json else None,
        "overall": parsed.get("overall", {}),
        "per_class": parsed.get("per_class", {}),
        "speed_ms_per_image": getattr(metrics, "speed", {}),
        "class_names": list(CLASS_NAMES),
        "note": (
            "本表是本项目 best.pt 在 v2 test split 上重测的结果；"
            "Roboflow 页面指标不作为本项目指标。"
        ),
    }
    run_dir = PATHS.project_dir
    report["training_progress"] = read_training_progress(run_dir / "results.csv")
    args = read_args_yaml(run_dir)
    report["train_args"] = {
        key: args.get(key)
        for key in ("model", "imgsz", "epochs", "batch", "patience", "seed", "workers", "amp", "data")
        if key in args
    }

    if analyze:
        report["ball_failure_analysis"] = analyze_test_split(
            weights, data_yaml=data_yaml, device=device, imgsz=imgsz
        )
        report["ball_size_distribution_public"] = collect_ball_sizes(
            PATHS.br_dir, PATHS.reports_dir / "ball_size_distribution.csv"
        )
        report["ball_size_distribution_bndstt"] = bndstt_ball_sizes()

    out = PATHS.reports_dir / "ball_racket_test_metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("saved: " + str(out))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="ball+racket 在 test split 上的正式评估")
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=INFER_IMGSZ)
    parser.add_argument("--split", default="test")
    parser.add_argument("--no-analyze", action="store_true")
    args = parser.parse_args(argv)

    run_eval(
        weights=args.weights,
        data_yaml=args.data,
        device=args.device,
        imgsz=args.imgsz,
        split=args.split,
        analyze=not args.no_analyze,
    )
    return 0


if __name__ == "__main__" or getattr(globals().get("_entry_module"), "__name__", "") == "__main__":
    sys.exit(main())
