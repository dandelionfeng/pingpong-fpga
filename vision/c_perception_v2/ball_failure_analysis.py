"""ball 专项 failure analysis（纯公开数据路线）。

只用 **公开 tableTennis v2 test split** 与 baseline v1 权重：
不使用任何 BNDSTT 人工标签、不训练、不做 RKNN。

分析维度
--------
1. **尺寸分桶**：按 GT ball 的像素宽高分桶，算每桶 recall（含 AP 意义上的匹配 IoU）；
2. **模糊分桶**：用 GT 框内 Laplacian 方差衡量清晰度，看 blur 对 recall 的影响；
3. **置信度分布**：命中 / 漏检各自的最高 conf，判断是“看不到”还是“置信度不够”；
4. **定位精度**：命中样本的 IoU 分布，判断漏检里有多少是“检到了但框偏”；
5. **空间分布**：漏检在画面中的位置（边缘 / 中央、上下半区）；
6. **尺寸 vs 阈值**：小球在不同 conf 下的 recall，给出可用阈值建议。

输出
----
* ``ball_failure_analysis.json``：全部结构化结果；
* ``ball_failure_report.md``：结论与建议；
* ``ball_recall_by_size.png`` / ``ball_recall_by_blur.png`` / ``ball_conf_distribution.png``；
* ``ball_failure_contact_sheet.jpg``：漏检样本（GT 对比）；
* ``ball_instances.csv``：每个 GT 实例一行，便于外部复核。
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
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
from .dataset_qa import contact_sheet, load_split_samples, read_image_robust, read_label_boxes, write_image_robust
from .yolo_io import (
    COLOR_BALL,
    Box,
    box_iou,
    draw_box,
    draw_label,
    draw_legend,
)

# 匹配口径
MATCH_IOU = 0.30          # 与上一轮 test_failures 保持一致
STRICT_IOU = 0.50         # AP50 意义上的严格匹配
CONF_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
SMALL_BALL_PX = 24.0      # 边长中位数以下视为小球（公开数据中位约 26.5 px）
EDGE_MARGIN_RATIO = 0.05  # 距画面边缘 5% 以内算“贴边”


def report_dir() -> Path:
    return PATHS.reports_dir / "BALL_FAILURE_ANALYSIS"


@dataclass
class Instance:
    image: str
    image_width: int
    image_height: int
    gt: Box
    matched: Box | None = None
    best_iou: float = 0.0
    best_conf: float | None = None
    laplacian_var: float = 0.0
    edge_distance_ratio: float = 1.0

    @property
    def width(self) -> float:
        return self.gt.width

    @property
    def height(self) -> float:
        return self.gt.height

    @property
    def side(self) -> float:
        return (self.gt.width + self.gt.height) / 2.0

    @property
    def area_ratio(self) -> float:
        return self.gt.area / float(self.image_width * self.image_height)

    @property
    def hit_loose(self) -> bool:
        return self.best_iou >= MATCH_IOU

    @property
    def hit_strict(self) -> bool:
        return self.best_iou >= STRICT_IOU


def blur_score(image, box: Box) -> float:
    """GT 框内 Laplacian 方差：越小越模糊。"""
    import cv2

    x1 = max(0, int(math.floor(box.x1)))
    y1 = max(0, int(math.floor(box.y1)))
    x2 = min(image.shape[1], int(math.ceil(box.x2)))
    y2 = min(image.shape[0], int(math.ceil(box.y2)))
    if x2 - x1 < 3 or y2 - y1 < 3:
        return 0.0
    crop = image[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def edge_ratio(box: Box, width: int, height: int) -> float:
    """框中心到最近画面边缘的距离，按短边归一化。"""
    cx, cy = box.center
    distance = min(cx, cy, width - cx, height - cy)
    return float(distance) / float(min(width, height))


def collect_instances(weights: Path, conf: float = 0.05) -> tuple[list[Instance], dict]:
    """对 test split 逐图推理，收集每个 GT ball 的匹配情况。"""
    from ultralytics import YOLO

    from .finetune_eval import predict_boxes

    samples = load_split_samples(PATHS.br_dir, "test")
    if not samples:
        raise FileNotFoundError("no test samples under " + str(PATHS.br_dir / "images" / "test"))
    model = YOLO(str(weights))
    instances: list[Instance] = []
    per_image: list[dict] = []
    total_pred_balls = 0

    for sample in samples:
        image = read_image_robust(sample.image_path)
        if image is None:
            continue
        gt_boxes, _ = read_label_boxes(sample)
        gt_balls = [b for b in gt_boxes if b.class_id == 0]
        preds = predict_boxes(model, image, conf=conf, imgsz=INFER_IMGSZ, iou=INFER_IOU, device=0)
        pred_balls = [b for b in preds if b.class_id == 0]
        total_pred_balls += len(pred_balls)

        unmatched = list(pred_balls)
        for gt in gt_balls:
            best, best_iou = None, 0.0
            for pred in unmatched:
                iou = box_iou(gt, pred)
                if iou > best_iou:
                    best, best_iou = pred, iou
            if best is not None and best_iou >= MATCH_IOU:
                unmatched.remove(best)
            instances.append(
                Instance(
                    image=sample.image_path.name,
                    image_width=sample.image_width,
                    image_height=sample.image_height,
                    gt=gt,
                    matched=best if best_iou >= MATCH_IOU else None,
                    best_iou=best_iou,
                    best_conf=best.confidence if best is not None else None,
                    laplacian_var=blur_score(image, gt),
                    edge_distance_ratio=edge_ratio(gt, sample.image_width, sample.image_height),
                )
            )
        per_image.append(
            {
                "image": sample.image_path.name,
                "ball_gt": len(gt_balls),
                "ball_pred": len(pred_balls),
                "ball_gt_sides": [round(b.width, 1) for b in gt_balls],
                "ball_pred_confs": [round(b.confidence, 4) for b in pred_balls],
            }
        )
    return instances, {
        "images": len(per_image),
        "gt_ball_instances": len(instances),
        "pred_ball_instances": total_pred_balls,
        "per_image": per_image,
    }


# ================================================================ 分桶
def _bucket_by_size(instances: list[Instance]) -> list[dict]:
    edges = [(0, 16), (16, 24), (24, 32), (32, 48), (48, 10_000)]
    rows = []
    for low, high in edges:
        group = [i for i in instances if low <= i.side < high]
        if not group:
            continue
        rows.append(_summarize_bucket(
            ("<" + str(high) if low == 0 else str(low) + "-" + str(high)) + " px",
            group,
        ))
    return rows


def _bucket_by_blur(instances: list[Instance]) -> list[dict]:
    values = sorted(i.laplacian_var for i in instances)
    if not values:
        return []

    def quantile(fraction: float) -> float:
        index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
        return values[index]

    q1, q2, q3 = quantile(0.25), quantile(0.50), quantile(0.75)
    edges = [
        ("very sharp (top 25%)", q3, float("inf")),
        ("sharp", q2, q3),
        ("blurry", q1, q2),
        ("very blurry (bottom 25%)", -1.0, q1),
    ]
    rows = []
    for label, low, high in edges:
        group = [i for i in instances if low <= i.laplacian_var < high]
        if group:
            row = _summarize_bucket(label, group)
            row["laplacian_range"] = [round(low, 2), None if high == float("inf") else round(high, 2)]
            rows.append(row)
    return rows


def _summarize_bucket(label: str, group: list[Instance]) -> dict:
    total = len(group)
    loose = sum(1 for i in group if i.hit_loose)
    strict = sum(1 for i in group if i.hit_strict)
    detected_but_missed = sum(
        1 for i in group if not i.hit_loose and i.best_iou > 0.0
    )
    return {
        "bucket": label,
        "instances": total,
        "recall_iou30": round(loose / total, 4),
        "recall_iou50": round(strict / total, 4),
        "detected_but_iou_below_threshold": detected_but_missed,
        "mean_best_iou": round(sum(i.best_iou for i in group) / total, 4),
        "mean_side_px": round(sum(i.side for i in group) / total, 2),
        "mean_laplacian": round(sum(i.laplacian_var for i in group) / total, 2),
    }


def _conf_distribution(instances: list[Instance]) -> dict:
    hits = [i.best_conf for i in instances if i.hit_loose and i.best_conf is not None]
    near = [i.best_conf for i in instances if not i.hit_loose and i.best_conf is not None]
    miss = [i for i in instances if i.best_conf is None]

    def pct(values: list[float], fraction: float):
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return round(ordered[index], 4)

    return {
        "hit_count": len(hits),
        "hit_conf_median": pct(hits, 0.5),
        "hit_conf_p10": pct(hits, 0.1),
        "hit_below_0_25": sum(1 for v in hits if v < 0.25),
        "hit_below_0_15": sum(1 for v in hits if v < 0.15),
        "ioU_below_threshold_but_detected": len(near),
        "ioU_below_threshold_conf_median": pct(near, 0.5),
        "no_prediction_near_gt": len(miss),
    }


def threshold_curve(weights: Path, confs=CONF_GRID) -> list[dict]:
    """不同 conf 下 ball 的实例召回与误检数（只算 ball）。"""
    from ultralytics import YOLO

    from .finetune_eval import predict_boxes

    samples = load_split_samples(PATHS.br_dir, "test")
    model = YOLO(str(weights))
    cache: list[tuple[object, list[Box], list[Box]]] = []
    for sample in samples:
        image = read_image_robust(sample.image_path)
        if image is None:
            continue
        gt_boxes, _ = read_label_boxes(sample)
        cache.append(
            (
                image,
                [b for b in gt_boxes if b.class_id == 0],
                predict_boxes(model, image, conf=min(confs), imgsz=INFER_IMGSZ, device=0),
            )
        )

    rows = []
    for conf in confs:
        gt_total = matched = fp = 0
        for _image, gt_balls, preds in cache:
            pred_balls = [b for b in preds if b.class_id == 0 and b.confidence >= conf]
            gt_total += len(gt_balls)
            unmatched = list(pred_balls)
            for gt in gt_balls:
                best, best_iou = None, 0.0
                for pred in unmatched:
                    iou = box_iou(gt, pred)
                    if iou > best_iou:
                        best, best_iou = pred, iou
                if best is not None and best_iou >= MATCH_IOU:
                    unmatched.remove(best)
                    matched += 1
            fp += len(unmatched)
        rows.append(
            {
                "conf": conf,
                "gt_instances": gt_total,
                "matched": matched,
                "false_positives": fp,
                "recall": round(matched / gt_total, 4) if gt_total else None,
                "precision": round(matched / (matched + fp), 4) if (matched + fp) else None,
            }
        )
    return rows


def _spatial(instances: list[Instance]) -> dict:
    edge = [i for i in instances if i.edge_distance_ratio < EDGE_MARGIN_RATIO]
    center = [i for i in instances if i.edge_distance_ratio >= EDGE_MARGIN_RATIO]
    top = [i for i in instances if i.gt.center[1] < i.image_height / 2]
    bottom = [i for i in instances if i.gt.center[1] >= i.image_height / 2]
    return {
        "edge_instances": len(edge),
        "edge_recall": round(sum(1 for i in edge if i.hit_loose) / len(edge), 4) if edge else None,
        "center_instances": len(center),
        "center_recall": round(sum(1 for i in center if i.hit_loose) / len(center), 4) if center else None,
        "top_recall": round(sum(1 for i in top if i.hit_loose) / len(top), 4) if top else None,
        "bottom_recall": round(sum(1 for i in bottom if i.hit_loose) / len(bottom), 4) if bottom else None,
    }


# ================================================================ 图表
def _plot_bars(rows: list[dict], x_key: str, y_keys: list[tuple[str, tuple[int, int, int]]],
               title: str, target: Path, note: str = "") -> bool:
    """用 OpenCV 画柱状图（避免额外依赖，且不受非 ASCII 路径写图问题影响）。"""
    import cv2
    import numpy as np

    if not rows:
        return False
    width, height = 980, 560
    canvas = np.full((height, width, 3), 250, dtype=np.uint8)
    left, right, top, bottom = 90, width - 40, 70, height - 90
    cv2.putText(canvas, title, (left, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (30, 30, 30), 2, cv2.LINE_AA)
    if note:
        cv2.putText(canvas, note, (left, height - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (90, 90, 90), 1, cv2.LINE_AA)
    # 轴
    cv2.line(canvas, (left, top), (left, bottom), (60, 60, 60), 2)
    cv2.line(canvas, (left, bottom), (right, bottom), (60, 60, 60), 2)
    for tick in range(0, 6):
        y = bottom - int((bottom - top) * tick / 5.0)
        cv2.line(canvas, (left - 6, y), (left, y), (60, 60, 60), 1)
        cv2.putText(canvas, format(tick / 5.0, ".1f"), (left - 52, y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 60), 1, cv2.LINE_AA)

    count = len(rows)
    slot = (right - left) / float(count)
    bar_width = slot / (len(y_keys) + 1.4)
    for index, row in enumerate(rows):
        base_x = left + slot * index + slot * 0.12
        for order, (key, color) in enumerate(y_keys):
            value = row.get(key)
            value = 0.0 if value is None else float(value)
            bar_h = int((bottom - top) * min(1.0, max(0.0, value)))
            x1 = int(base_x + order * bar_width)
            x2 = int(x1 + bar_width * 0.92)
            cv2.rectangle(canvas, (x1, bottom - bar_h), (x2, bottom), color, -1)
            cv2.putText(canvas, format(value, ".2f"), (x1, bottom - bar_h - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (40, 40, 40), 1, cv2.LINE_AA)
        label = str(row.get(x_key, ""))
        cv2.putText(canvas, label[:18], (int(left + slot * index + 2), bottom + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)
        n_key = "instances"
        if n_key in row:
            cv2.putText(canvas, "n=" + str(row[n_key]), (int(left + slot * index + 2), bottom + 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1, cv2.LINE_AA)
    # 图例
    legend_x = left + 10
    for key, color in y_keys:
        cv2.rectangle(canvas, (legend_x, top - 26), (legend_x + 14, top - 14), color, -1)
        cv2.putText(canvas, key, (legend_x + 20, top - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                    (40, 40, 40), 1, cv2.LINE_AA)
        legend_x += 26 + 9 * len(key)
    return write_image_robust(target, canvas)


def _contact_sheet(instances: list[Instance], target: Path, max_panels: int = 32) -> bool:
    by_image: dict[str, list[Instance]] = {}
    for inst in instances:
        if inst.hit_loose:
            continue
        by_image.setdefault(inst.image, []).append(inst)
    panels = []
    for image_name, group in sorted(by_image.items())[:max_panels]:
        sample = next(
            (s for s in load_split_samples(PATHS.br_dir, "test") if s.image_path.name == image_name),
            None,
        )
        if sample is None:
            continue
        image = read_image_robust(sample.image_path)
        if image is None:
            continue
        canvas = image.copy()
        gt_boxes, _ = read_label_boxes(sample)
        for box in [b for b in gt_boxes if b.class_id == 1]:
            draw_box(canvas, box, label="GT racket", color=(120, 200, 120), thickness=1)
        for inst in group:
            side = format(inst.side, ".0f")
            draw_box(canvas, inst.gt,
                     label="GT ball " + side + "px iou=" + format(inst.best_iou, ".2f"),
                     color=COLOR_BALL, thickness=2)
        draw_legend(canvas, [("missed ball (GT)", COLOR_BALL)])
        draw_label(canvas, image_name[-34:], (8, canvas.shape[0] - 26), (45, 45, 45), scale=0.5)
        panels.append(canvas)
    if not panels:
        return False
    return write_image_robust(target, contact_sheet(panels, columns=6, panel_width=620))


# ================================================================ 主流程
def run_analysis(weights: Path | None = None, conf: float = 0.05) -> dict:
    weights = Path(weights) if weights else PATHS.model_out_dir / "best.pt"
    if not weights.is_file():
        raise FileNotFoundError("weights not found: " + str(weights))
    out = report_dir()
    out.mkdir(parents=True, exist_ok=True)

    instances, meta = collect_instances(weights, conf=conf)
    by_size = _bucket_by_size(instances)
    by_blur = _bucket_by_blur(instances)
    conf_dist = _conf_distribution(instances)
    spatial = _spatial(instances)
    curve = threshold_curve(weights)

    # 实例级 CSV
    csv_path = out / "ball_instances.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "image", "gt_x1", "gt_y1", "gt_x2", "gt_y2", "side_px", "area_ratio",
            "best_iou", "best_conf", "hit_iou30", "hit_iou50", "laplacian_var",
            "edge_distance_ratio", "gt_center_x", "gt_center_y",
        ])
        for inst in instances:
            writer.writerow([
                inst.image, *[round(v, 2) for v in inst.gt.to_xyxy()],
                round(inst.side, 2), round(inst.area_ratio, 8), round(inst.best_iou, 4),
                None if inst.best_conf is None else round(inst.best_conf, 4),
                int(inst.hit_loose), int(inst.hit_strict), round(inst.laplacian_var, 2),
                round(inst.edge_distance_ratio, 4),
                round(inst.gt.center[0], 1), round(inst.gt.center[1], 1),
            ])

    charts = {
        "by_size": _plot_bars(
            by_size, "bucket", [("recall_iou30", (60, 150, 240)), ("recall_iou50", (200, 140, 60))],
            "ball recall by GT bbox size (public test)",
            out / "ball_recall_by_size.png",
            "recall_iou30 = match IoU>=0.30 ; recall_iou50 = AP50-style IoU>=0.50",
        ),
        "by_blur": _plot_bars(
            by_blur, "bucket", [("recall_iou30", (60, 150, 240))],
            "ball recall by sharpness (Laplacian var in GT box)",
            out / "ball_recall_by_blur.png",
            "lower Laplacian variance = more motion blur / defocus",
        ),
        "conf": _plot_bars(
            [{"bucket": format(r["conf"], ".2f"), "recall": r["recall"],
              "precision": r["precision"], "instances": r["gt_instances"]} for r in curve],
            "bucket", [("recall", (60, 150, 240)), ("precision", (200, 140, 60))],
            "ball instance recall / precision vs conf (public test)",
            out / "ball_conf_curve.png",
            "computed on cached predictions at conf>=0.05",
        ),
    }
    sheet_ok = _contact_sheet(instances, out / "ball_failure_contact_sheet.jpg")

    total = len(instances)
    hit = sum(1 for i in instances if i.hit_loose)
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weights": str(weights),
        "dataset": str(PATHS.br_dir),
        "split": "test",
        "note": "只用公开 tableTennis v2 test split；未使用任何 BNDSTT 人工标签",
        "match_iou": MATCH_IOU,
        "strict_iou": STRICT_IOU,
        "inference_conf_floor": conf,
        "summary": {
            "gt_ball_instances": total,
            "matched_iou30": hit,
            "recall_iou30": round(hit / total, 4) if total else None,
            "matched_iou50": sum(1 for i in instances if i.hit_strict),
            "recall_iou50": round(sum(1 for i in instances if i.hit_strict) / total, 4) if total else None,
            "pred_ball_instances": meta["pred_ball_instances"],
            "test_images": meta["images"],
        },
        "by_size": by_size,
        "by_blur": by_blur,
        "conf_distribution": conf_dist,
        "spatial": spatial,
        "threshold_curve": curve,
        "charts_written": charts,
        "contact_sheet": str(out / "ball_failure_contact_sheet.jpg") if sheet_ok else None,
        "instances_csv": str(csv_path),
    }
    (out / "ball_failure_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_markdown(result, out / "ball_failure_report.md")
    return result


def _write_markdown(result: dict, path: Path) -> None:
    s = result["summary"]
    lines = [
        "# ball 专项 failure analysis（公开 test split）",
        "",
        "生成时间：" + result["generated_at_utc"],
        "权重：`" + result["weights"] + "`",
        "口径：匹配 IoU >= " + str(result["match_iou"]) + "（严格 " + str(result["strict_iou"]) + "）",
        "说明：" + result["note"],
        "",
        "## 总体",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        "| GT ball 实例 | " + str(s["gt_ball_instances"]) + " |",
        "| 命中 (IoU>=0.30) | " + str(s["matched_iou30"]) + " → recall " + str(s["recall_iou30"]) + " |",
        "| 命中 (IoU>=0.50) | " + str(s["matched_iou50"]) + " → recall " + str(s["recall_iou50"]) + " |",
        "| 预测 ball 框总数 | " + str(s["pred_ball_instances"]) + " |",
        "",
        "## 按球尺寸分桶",
        "",
        "| 桶 | 实例 | recall@0.30 | recall@0.50 | 检到但框偏 | 平均 best-IoU | 平均边长 px |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["by_size"]:
        lines.append(
            "| " + row["bucket"] + " | " + str(row["instances"]) + " | " + str(row["recall_iou30"])
            + " | " + str(row["recall_iou50"]) + " | " + str(row["detected_but_iou_below_threshold"])
            + " | " + str(row["mean_best_iou"]) + " | " + str(row["mean_side_px"]) + " |"
        )
    lines += ["", "## 按清晰度分桶（框内 Laplacian 方差）", "",
              "| 桶 | 实例 | recall@0.30 | 平均 best-IoU | 平均边长 px |",
              "| --- | --- | --- | --- | --- |"]
    for row in result["by_blur"]:
        lines.append(
            "| " + row["bucket"] + " | " + str(row["instances"]) + " | " + str(row["recall_iou30"])
            + " | " + str(row["mean_best_iou"]) + " | " + str(row["mean_side_px"]) + " |"
        )
    cd = result["conf_distribution"]
    lines += [
        "", "## 置信度分布（判断“看不到”还是“置信度不够”）", "",
        "- 命中实例数：" + str(cd["hit_count"]),
        "- 命中实例 conf 中位：" + str(cd["hit_conf_median"]) + "，P10：" + str(cd["hit_conf_p10"]),
        "- 命中但 conf < 0.25 的数量：**" + str(cd["hit_below_0_25"]) + "**",
        "- 命中但 conf < 0.15 的数量：**" + str(cd["hit_below_0_15"]) + "**",
        "- 附近有框但 IoU 不足阈值：" + str(cd["ioU_below_threshold_but_detected"]),
        "- **GT 附近完全没有预测框**：" + str(cd["no_prediction_near_gt"]),
        "",
        "## 空间分布", "",
        "| 区域 | 实例 | recall@0.30 |", "| --- | --- | --- |",
        "| 贴边（距边缘<5%） | " + str(result["spatial"]["edge_instances"]) + " | "
        + str(result["spatial"]["edge_recall"]) + " |",
        "| 中央 | " + str(result["spatial"]["center_instances"]) + " | "
        + str(result["spatial"]["center_recall"]) + " |",
        "| 上半画面 | - | " + str(result["spatial"]["top_recall"]) + " |",
        "| 下半画面 | - | " + str(result["spatial"]["bottom_recall"]) + " |",
        "",
        "## 阈值曲线（ball 实例级）", "",
        "| conf | GT | 命中 | 误检 | recall | precision |", "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["threshold_curve"]:
        lines.append(
            "| " + format(row["conf"], ".2f") + " | " + str(row["gt_instances"]) + " | "
            + str(row["matched"]) + " | " + str(row["false_positives"]) + " | "
            + str(row["recall"]) + " | " + str(row["precision"]) + " |"
        )
    lines += ["", "## 图表", ""]
    for key, ok in result["charts_written"].items():
        lines.append("- " + key + "：" + ("已生成" if ok else "未生成"))
    if result.get("contact_sheet"):
        lines.append("- 漏检 contact sheet：" + result["contact_sheet"])
    lines += ["", "实例级明细：" + result["instances_csv"], ""]
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="ball 专项 failure analysis（公开 test split）")
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--conf", type=float, default=0.05, help="收集预测时的 conf 下限")
    args = parser.parse_args(argv)
    result = run_analysis(weights=args.weights, conf=args.conf)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("report: " + str(report_dir() / "ball_failure_report.md"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
