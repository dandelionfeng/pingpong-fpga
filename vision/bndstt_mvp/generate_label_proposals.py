"""Generate review-only annotation proposals; never writes ground-truth labels."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import torch
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
PROPOSALS = DATASET / "proposals"
MODELS = ROOT / "artifacts/files/models/ultralytics"


def clamp_box(box: list[float], width: int, height: int) -> list[float]:
    x1, y1, x2, y2 = box
    return [max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2)]


def iou(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ab = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / max(aa + ab - inter, 1e-9)


def add_deduplicated(items: list[dict], candidate: dict, threshold: float = 0.55) -> None:
    for existing in items:
        if existing["class_id"] == candidate["class_id"] and iou(existing["xyxy"], candidate["xyxy"]) >= threshold:
            if candidate["confidence"] > existing["confidence"]:
                existing.update(candidate)
            return
    items.append(candidate)


def main() -> None:
    PROPOSALS.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((DATASET / "frames_manifest.csv").open(encoding="utf-8-sig")))
    images = [str(DATASET / row["original_image_path"]) for row in rows]

    device = 0 if torch.cuda.is_available() else "cpu"
    detector = YOLO(str(MODELS / "yolov8x.pt"))
    poser = YOLO(str(MODELS / "yolov8n-pose.pt"))
    # Keep the one-off CUDA proposal pass inside the 8 GiB laptop GPU budget.
    # These outputs remain review-only candidates; they are never promoted to GT
    # without visual confirmation.
    detections = detector.predict(
        images, imgsz=960, conf=0.03, iou=0.5, classes=[32, 38],
        device=device, batch=1, half=device != "cpu", verbose=False,
    )
    poses = poser.predict(
        images, imgsz=960, conf=0.15, iou=0.5,
        device=device, batch=2, half=device != "cpu", verbose=False,
    )

    proposal_document: list[dict] = []
    for row, det_result, pose_result in zip(rows, detections, poses):
        width, height = int(row["width"]), int(row["height"])
        items: list[dict] = []
        if det_result.boxes is not None:
            for box, cls, conf in zip(det_result.boxes.xyxy.tolist(), det_result.boxes.cls.tolist(), det_result.boxes.conf.tolist()):
                class_id = 0 if int(cls) == 32 else 2
                add_deduplicated(items, {
                    "class_id": class_id,
                    "xyxy": clamp_box([float(v) for v in box], width, height),
                    "confidence": float(conf),
                    "proposal_source": "coco_yolov8n_sports_ball" if class_id == 0 else "coco_yolov8n_tennis_racket",
                })

        if pose_result.keypoints is not None and pose_result.boxes is not None:
            xy = pose_result.keypoints.xy.tolist()
            confidences = pose_result.keypoints.conf.tolist() if pose_result.keypoints.conf is not None else []
            person_boxes = pose_result.boxes.xyxy.tolist()
            person_scores = pose_result.boxes.conf.tolist()
            for person_index, (keypoints, person_box, person_score) in enumerate(zip(xy, person_boxes, person_scores)):
                kp_conf = confidences[person_index] if person_index < len(confidences) else [1.0] * len(keypoints)
                person_width = max(1.0, person_box[2] - person_box[0])
                person_height = max(1.0, person_box[3] - person_box[1])
                for wrist_idx, elbow_idx, side in ((9, 7, "left"), (10, 8, "right")):
                    if wrist_idx >= len(keypoints) or elbow_idx >= len(keypoints):
                        continue
                    if kp_conf[wrist_idx] < 0.18 or kp_conf[elbow_idx] < 0.12:
                        continue
                    wx, wy = keypoints[wrist_idx]
                    ex, ey = keypoints[elbow_idx]
                    forearm = math.hypot(wx - ex, wy - ey)
                    if forearm < 2:
                        continue
                    cx = wx + 0.12 * (wx - ex)
                    cy = wy + 0.12 * (wy - ey)
                    side_px = max(16.0, min(0.18 * person_width + 0.08 * person_height, 0.52 * forearm))
                    hand_box = clamp_box([cx - side_px / 2, cy - side_px / 2, cx + side_px / 2, cy + side_px / 2], width, height)
                    add_deduplicated(items, {
                        "class_id": 1,
                        "xyxy": hand_box,
                        "confidence": float(min(person_score, kp_conf[wrist_idx])),
                        "proposal_source": f"coco_yolov8n_pose_{side}_wrist_geometry",
                    })

        proposal_document.append({
            "derived_gray3_path": row["derived_gray3_path"],
            "original_image_path": row["original_image_path"],
            "source_id": row["source_id"],
            "session_id": row["session_id"],
            "split": row["split"],
            "frame_index": int(row["frame_index"]),
            "timestamp_seconds": float(row["timestamp_seconds"]),
            "width": width,
            "height": height,
            "proposals": items,
            "review_status": "proposal_only_not_ground_truth",
        })

    (PROPOSALS / "proposals.json").write_text(json.dumps({
        "status": "AUTO PROPOSALS ONLY - NOT GROUND TRUTH",
        "detector": "yolov8x.pt COCO classes sports ball / tennis racket (review-only helper)",
        "hand_helper": "yolov8n-pose.pt wrist geometry",
        "device": str(device),
        "items": proposal_document,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {0: 0, 1: 0, 2: 0}
    for item in proposal_document:
        for box in item["proposals"]:
            counts[box["class_id"]] += 1
    print(json.dumps({"images": len(proposal_document), "proposal_counts": counts}, indent=2))


if __name__ == "__main__":
    main()
