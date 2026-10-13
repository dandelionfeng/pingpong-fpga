"""正式 inference operating point 分析与选择（PART A）。

设计要点
--------
* **一次推理，离线扫描**：模型用 ``base_conf``（默认 0.02）预测并缓存全部候选，
  然后在 Python 里分别套用 class-specific 阈值。切换阈值不需要重跑 GPU。
* **class-specific**：ball 与 racket 任务需求不同，各自独立阈值，不共享。
* **固定阈值指标**：在公开 test（有真 GT）上算 TP/FP/FN/P/R/F1，
  匹配为 **one-to-one greedy（按 confidence 从高到低）**，IoU 阈值 0.50。
  一个 prediction 只能匹配一个 GT。
* **不混淆 AP 与固定阈值指标**：不对每个 conf 生成 “mAP@conf”。
  原始 AP50 / mAP50 / mAP50-95 继续作为模型整体指标单独记录。
* **BNDSTT_30 只算 coverage**：该集无完整 verified GT，禁止输出 P/R/AP。
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import INFER_IMGSZ, INFER_IOU, PATHS
from .dataset_qa import load_split_samples, read_image_robust, read_label_boxes
from .finetune_eval import predict_boxes
from .finetune_domain import read_csv_rows
from .yolo_io import Box, box_iou

BASE_CONF = 0.02
MATCH_IOU = 0.50
BALL_THRESHOLDS = (0.03, 0.05, 0.075, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30)
RACKET_THRESHOLDS = (0.05, 0.075, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
GLOBAL_THRESHOLDS = (0.05, 0.10, 0.15, 0.25)

# 两类别的阈值网格相互独立（不共享同一阈值）
THRESHOLD_GRID_IS_SHARED = False
CLASS_NAMES = {0: "ball", 1: "racket"}
CLASS_BALL, CLASS_RACKET = 0, 1


def report_dir() -> Path:
    return PATHS.reports_dir / "OPERATING_POINT_V1"


# ================================================================ 候选缓存
@dataclass
class CachedDetection:
    image_id: str
    image_width: int
    image_height: int
    class_id: int
    confidence: float
    bbox_xyxy: list[float]


@dataclass
class GroundTruth:
    image_id: str
    class_id: int
    bbox_xyxy: list[float]


def cache_public_test(weights: Path, base_conf: float = BASE_CONF,
                      device: str | int = 0) -> dict:
    """在公开 test split 上一次性低阈值推理，缓存全部候选与 GT。"""
    from ultralytics import YOLO

    weights = Path(weights)
    if not weights.is_file():
        raise FileNotFoundError("weights not found: " + str(weights))
    samples = load_split_samples(PATHS.br_dir, "test")
    if not samples:
        raise FileNotFoundError("public test split not found under " + str(PATHS.br_dir))
    model = YOLO(str(weights))

    detections: list[dict] = []
    ground_truth: list[dict] = []
    for sample in samples:
        image = read_image_robust(sample.image_path)
        if image is None:
            continue
        gt_boxes, _ = read_label_boxes(sample)
        for gt in gt_boxes:
            if gt.class_id in CLASS_NAMES:
                ground_truth.append(
                    {
                        "image_id": sample.image_path.stem,
                        "class_id": int(gt.class_id),
                        "bbox_xyxy": [round(v, 3) for v in gt.to_xyxy()],
                    }
                )
        preds = predict_boxes(model, image, conf=base_conf, imgsz=INFER_IMGSZ,
                              iou=INFER_IOU, device=device)
        for pred in preds:
            if pred.class_id not in CLASS_NAMES:
                continue
            detections.append(
                {
                    "image_id": sample.image_path.stem,
                    "image_width": sample.image_width,
                    "image_height": sample.image_height,
                    "class_id": int(pred.class_id),
                    "confidence": round(float(pred.confidence), 6),
                    "bbox_xyxy": [round(v, 3) for v in pred.to_xyxy()],
                }
            )
    return {
        "weights": str(weights),
        "base_conf": base_conf,
        "match_iou": MATCH_IOU,
        "images": len(samples),
        "detections": detections,
        "ground_truth": ground_truth,
    }


def save_cache(cache: dict, path: Path | None = None) -> Path:
    target = Path(path) if path else (report_dir() / "public_test_candidates_base002.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return target


def load_cache(path: Path | None = None) -> dict:
    target = Path(path) if path else (report_dir() / "public_test_candidates_base002.json")
    if not target.is_file():
        raise FileNotFoundError("candidate cache not found: " + str(target))
    return json.loads(target.read_text(encoding="utf-8"))


# ================================================================ 固定阈值指标
def match_one_to_one(
    predictions: list[dict], ground_truth: list[dict], match_iou: float = MATCH_IOU
) -> dict:
    """one-to-one greedy 匹配：prediction 按 confidence 降序，每个 GT 最多匹配一次。

    与 COCO 一致的贪心实现：对每个 prediction，找当前未被占用的、IoU 最大的 GT。
    """
    ordered = sorted(predictions, key=lambda p: -p["confidence"])
    available = list(ground_truth)
    tp = 0
    matched_iou: list[float] = []
    for pred in ordered:
        pred_box = Box(*pred["bbox_xyxy"], class_id=pred["class_id"])
        best_index, best_iou = -1, 0.0
        for index, gt in enumerate(available):
            iou = box_iou(pred_box, Box(*gt["bbox_xyxy"], class_id=gt["class_id"]))
            if iou > best_iou:
                best_index, best_iou = index, iou
        if best_index >= 0 and best_iou >= match_iou:
            tp += 1
            matched_iou.append(best_iou)
            available.pop(best_index)
    fp = len(ordered) - tp
    fn = len(available)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )
    matched_iou.sort()
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "detections": len(ordered),
        "gt_instances": len(ground_truth),
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "matched_iou_median": (
            round(matched_iou[len(matched_iou) // 2], 4) if matched_iou else None
        ),
    }


def fixed_threshold_metrics(
    cache: dict, class_id: int, threshold: float, match_iou: float = MATCH_IOU
) -> dict:
    """对指定类别套用固定阈值后计算 P/R/F1。"""
    predictions = [
        d
        for d in cache["detections"]
        if d["class_id"] == class_id and d["confidence"] >= threshold
    ]
    ground_truth = [g for g in cache["ground_truth"] if g["class_id"] == class_id]
    result = match_one_to_one(predictions, ground_truth, match_iou=match_iou)
    result["class_id"] = class_id
    result["class_name"] = CLASS_NAMES[class_id]
    result["threshold"] = threshold
    return result


def threshold_curve(cache: dict, class_id: int, thresholds) -> list[dict]:
    return [fixed_threshold_metrics(cache, class_id, t) for t in thresholds]


def global_threshold_metrics(cache: dict, threshold: float) -> dict:
    """global conf 参考：两类共用同一阈值。"""
    out = {"threshold": threshold}
    for class_id in (CLASS_BALL, CLASS_RACKET):
        out[CLASS_NAMES[class_id]] = fixed_threshold_metrics(cache, class_id, threshold)
    return out


# ================================================================ BNDSTT_30 coverage
def bndstt30_coverage(weights: Path, ball_conf: float, racket_conf: float,
                      device: str | int = 0) -> dict:
    """BNDSTT_30 上的 **detection COVERAGE**（不是 recall）。

    该集无完整 verified GT，因此只统计结构性覆盖指标。
    """
    from ultralytics import YOLO

    rows = read_csv_rows(PATHS.benchmark_manifest)
    model = YOLO(str(weights))
    ball_frames = racket_frames = both_frames = 0
    ball_total = racket_total = 0
    multi_ball = multi_racket = 0
    per_frame: list[dict] = []
    for row in rows:
        image = read_image_robust(Path(row["image_path"]))
        if image is None:
            continue
        preds = predict_boxes(model, image, conf=min(ball_conf, racket_conf), imgsz=INFER_IMGSZ,
                              iou=INFER_IOU, device=device)
        balls = [p for p in preds if p.class_id == CLASS_BALL and p.confidence >= ball_conf]
        rackets = [p for p in preds
                   if p.class_id == CLASS_RACKET and p.confidence >= racket_conf]
        if balls:
            ball_frames += 1
        if rackets:
            racket_frames += 1
        if balls and rackets:
            both_frames += 1
        if len(balls) > 1:
            multi_ball += 1
        if len(rackets) > 1:
            multi_racket += 1
        ball_total += len(balls)
        racket_total += len(rackets)
        per_frame.append(
            {
                "image_id": row["image_id"],
                "stage_hint": row.get("stage_hint", ""),
                "ball_candidates": len(balls),
                "racket_candidates": len(rackets),
            }
        )
    total = len(per_frame)
    return {
        "dataset": "BNDSTT_30_V1",
        "metric_type": "DETECTION_COVERAGE_NOT_RECALL",
        "no_ground_truth": True,
        "forbidden_metrics": ["precision", "recall", "AP", "mAP", "accuracy"],
        "ball_conf": ball_conf,
        "racket_conf": racket_conf,
        "frames": total,
        "ball_coverage_frames": ball_frames,
        "racket_coverage_frames": racket_frames,
        "both_coverage_frames": both_frames,
        "ball_coverage_ratio_frames": round(ball_frames / total, 4) if total else None,
        "racket_coverage_ratio_frames": round(racket_frames / total, 4) if total else None,
        "both_coverage_ratio_frames": round(both_frames / total, 4) if total else None,
        "ball_candidate_count": ball_total,
        "racket_candidate_count": racket_total,
        "multi_ball_frames": multi_ball,
        "multi_racket_frames": multi_racket,
        "per_frame": per_frame,
    }


def bndstt30_threshold_matrix(weights: Path, ball_confs=BALL_THRESHOLDS,
                              racket_confs=RACKET_THRESHOLDS,
                              device: str | int = 0) -> list[dict]:
    """ball_conf × racket_conf 完整组合扫描（只算 coverage）。"""
    from ultralytics import YOLO

    rows = read_csv_rows(PATHS.benchmark_manifest)
    model = YOLO(str(weights))
    # 先用最低阈值缓存每帧候选
    minimum = min(min(ball_confs), min(racket_confs))
    frames: list[dict] = []
    for row in rows:
        image = read_image_robust(Path(row["image_path"]))
        if image is None:
            continue
        preds = predict_boxes(model, image, conf=minimum, imgsz=INFER_IMGSZ,
                              iou=INFER_IOU, device=device)
        frames.append(
            {
                "ball": [p.confidence for p in preds if p.class_id == CLASS_BALL],
                "racket": [p.confidence for p in preds if p.class_id == CLASS_RACKET],
            }
        )
    matrix: list[dict] = []
    for bconf in ball_confs:
        for rconf in racket_confs:
            ball_frames = sum(1 for f in frames if any(c >= bconf for c in f["ball"]))
            racket_frames = sum(1 for f in frames if any(c >= rconf for c in f["racket"]))
            both_frames = sum(
                1
                for f in frames
                if any(c >= bconf for c in f["ball"]) and any(c >= rconf for c in f["racket"])
            )
            matrix.append(
                {
                    "ball_conf": bconf,
                    "racket_conf": rconf,
                    "ball_coverage": ball_frames,
                    "racket_coverage": racket_frames,
                    "both_coverage": both_frames,
                    "ball_candidate_count": sum(
                        1 for f in frames for c in f["ball"] if c >= bconf
                    ),
                    "racket_candidate_count": sum(
                        1 for f in frames for c in f["racket"] if c >= rconf
                    ),
                    "multi_ball_frames": sum(
                        1 for f in frames if sum(1 for c in f["ball"] if c >= bconf) > 1
                    ),
                    "multi_racket_frames": sum(
                        1 for f in frames if sum(1 for c in f["racket"] if c >= rconf) > 1
                    ),
                }
            )
    return matrix


# ================================================================ profile 选择
def set_coverage_table(table: dict) -> None:
    """由 runner 注入 {(threshold, class_name): coverage} 供 profile 规则查表。"""
    globals()["_COVERAGE_TABLE"] = dict(table)


def _coverage(threshold: float, class_name: str) -> int:
    """查已缓存的 BNDSTT_30 coverage。

    未注入时返回 0，使带 coverage 下限的规则**拒绝**所有候选并回退到默认分支，
    避免静默地绕过约束。
    """
    table = globals().get("_COVERAGE_TABLE") or {}
    return int(table.get((round(float(threshold), 4), class_name), 0))


def select_profiles(cache: dict) -> dict:
    """基于公开 test 固定阈值曲线 + BNDSTT_30 coverage 选择三个 profile。

    规则（可复算，写在报告里）：
      HIGH_RECALL    : 每类取 recall 最大者（并列时取阈值更大=precision 更高者）。
      BALANCED       : 以**部署域（BNDSTT_30）coverage 下限**为硬约束，在满足约束的阈值中取
                       recall/F1 最优：
                         ball   : coverage >= 19/30 的前提下 recall 最大者，
                                  并要求 public test precision >= 0.50（低于 0.50 视为高风险）；
                         racket : coverage >= 17/30 的前提下 F1 最大者。
      HIGH_PRECISION : 每类取 precision >= 0.85 的最小阈值（未达则取 precision 最高者）。

    为什么 BALANCED 不直接取公开 test 最优：域内置信度系统性偏低，
    纯按公开 test 选阈值会让域内 coverage 崩掉（example: racket_conf 0.4 → coverage 13/30）。
    """
    ball_curve = threshold_curve(cache, CLASS_BALL, BALL_THRESHOLDS)
    racket_curve = threshold_curve(cache, CLASS_RACKET, RACKET_THRESHOLDS)

    def best_by(curve, key, predicate=None):
        pool = [row for row in curve if (predicate(row) if predicate else True)]
        fell_back = not pool
        if fell_back:
            pool = curve
        chosen = max(pool, key=lambda row: (row[key] if row[key] is not None else -1,
                                            -row["threshold"]))
        chosen = dict(chosen)
        chosen["_rule_fallback"] = fell_back
        return chosen

    def lowest_with(curve, key, target):
        pool = [row for row in curve if (row[key] or 0) >= target]
        if not pool:
            chosen = max(curve, key=lambda row: (row[key] or 0))
        else:
            chosen = min(pool, key=lambda row: row["threshold"])
        return dict(chosen)

    high_recall_ball = best_by(ball_curve, "recall")
    high_recall_racket = best_by(racket_curve, "recall")

    balanced_ball = best_by(
        ball_curve,
        "recall",
        predicate=lambda r: _coverage(r["threshold"], "ball") >= 19 and (r["precision"] or 0) >= 0.50,
    )
    balanced_racket = best_by(
        racket_curve,
        "f1",
        predicate=lambda r: _coverage(r["threshold"], "racket") >= 17,
    )

    high_prec_ball = lowest_with(ball_curve, "precision", 0.85)
    high_prec_racket = lowest_with(racket_curve, "precision", 0.85)

    def pack(ball_row, racket_row):
        return {
            "ball_conf": ball_row["threshold"],
            "racket_conf": racket_row["threshold"],
            "ball_metrics": ball_row,
            "racket_metrics": racket_row,
            "ball_coverage_bndstt30": _coverage(ball_row["threshold"], "ball"),
            "racket_coverage_bndstt30": _coverage(racket_row["threshold"], "racket"),
        }

    return {
        "PROFILE_HIGH_RECALL": pack(high_recall_ball, high_recall_racket),
        "PROFILE_BALANCED": pack(balanced_ball, balanced_racket),
        "PROFILE_HIGH_PRECISION": pack(high_prec_ball, high_prec_racket),
        "curves": {"ball": ball_curve, "racket": racket_curve},
        "rules": {
            "HIGH_RECALL": "per class: max recall; tie-break to larger threshold (higher precision)",
            "BALANCED": (
                "ball: max recall subject to BNDSTT_30 coverage>=19/30 AND public-test precision>=0.50; "
                "racket: max F1 subject to BNDSTT_30 coverage>=17/30"
            ),
            "HIGH_PRECISION": "per class: lowest threshold reaching precision>=0.85",
        },
        "precision_risk_flag": "public-test precision < 0.50 is treated as high risk",
        "fallback_flags": {
            "BALANCED_ball_fallback": balanced_ball.get("_rule_fallback", False),
            "BALANCED_racket_fallback": balanced_racket.get("_rule_fallback", False),
        },
    }

