"""PART B/A/F: gray3 (GRAY8 -> replicate 3ch) verification for the OV9281 deployment path.

Why this file exists
--------------------
The real camera chain (A side) hands C a **single-channel GRAY8** image, not BGR.
BallTrack was bake-off tested with colour frames. That colour result cannot be
reported as an OV9281 deployment number, so this module re-runs the comparison
with the ONLY change being:

    colour frame  ->  grayscale  ->  replicated to 3 identical channels

Official input contract (verified from the official sources, not assumed)
------------------------------------------------------------------------
* `source/BallTrack/configs/tracknetv3_base.py`: `seq_len = 4`, `width = 512`,
  `height = 288`, `bg_mode = 'concat'`, `last_only = True`.
* `source/BallTrack/inference.py` `_preprocess_batch`:
      data = concat([median, moveaxis(seq, -1, 1)], 0)   # median first, then frames
  and `fids = [max(0, j) for j in range(i - seq_len, i)]` -> the LAST frame of the
  sample is frame `i-1`, so the prediction for frame `i` uses frames i-4..i-1.
* Exported ONNX input `[1, 15, 288, 512]` == 3 * (4 frames + 1 median), output
  `[1, 1, 288, 512]` (single heatmap because `last_only=True`).

So 15 channels are NOT one frame copied 15 times: they are
``[median(3ch), frame_{i-4}(3ch), frame_{i-3}(3ch), frame_{i-2}(3ch), frame_{i-1}(3ch)]``.
For gray3 deployment EACH of those five items is a different gray frame replicated
to 3 channels.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

from .ball_bakeoff import (
    BALLTRACK_H,
    BALLTRACK_SEQ_LEN,
    BALLTRACK_THRE,
    BALLTRACK_W,
    BallGt,
    _extract_video_frames,
    balltrack_root,
    decode_heatmap,
    load_manual_ball_gt,
    percentile,
    report_dir as bakeoff_dir,
    score,
)
from .config import INFER_IMGSZ, INFER_IOU, PATHS
from .dataset_qa import read_image_robust

GRAY3_DIR_NAME = "GRAY3_FINAL_VALIDATION"


def gray3_dir() -> Path:
    return PATHS.reports_dir / GRAY3_DIR_NAME


def to_gray3(bgr):
    """BGR/RGB -> single channel -> 3 identical channels (values equal, so order is moot)."""
    import cv2

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def build_balltrack_input(gt: BallGt, median_path: Path, mode: str):
    """Assemble the official (15, 288, 512) tensor for the center frame.

    mode = "color" -> raw BGR frames + colour median
    mode = "gray3" -> every frame AND the median pass through gray -> 3ch first
    """
    import cv2
    import numpy as np

    if gt.source_video is None:
        return None

    center = gt.frame_index
    span = BALLTRACK_SEQ_LEN + 4  # a little extra context so spacing stays honest
    indices = list(range(center - span, center + 1))
    frames_by_index = _extract_video_frames(gt.source_video, indices)
    if center not in frames_by_index:
        return None

    # Official semantics: the sample whose last frame is `center` uses center-4 .. center-1.
    # We therefore need those four frames plus the frame we score.
    needed = [max(0, center - BALLTRACK_SEQ_LEN + k) for k in range(BALLTRACK_SEQ_LEN)]
    seq = []
    for idx in needed:
        if idx in frames_by_index:
            frame = frames_by_index[idx]
        else:
            nearest = min(frames_by_index, key=lambda k: abs(k - idx))
            frame = frames_by_index[nearest]
        if mode == "gray3":
            frame = to_gray3(frame)
        seq.append(cv2.resize(frame, (BALLTRACK_W, BALLTRACK_H)))
    seq = np.array(seq, dtype=np.float32) / 255.0

    median = np.load(median_path)["median"]
    if mode == "gray3":
        # 灰度中位数缓存里存的已经是 2D 单通道图；彩色缓存是 3 通道 RGB
        if median.ndim == 3 and median.shape[2] == 3:
            median = cv2.cvtColor(median, cv2.COLOR_RGB2GRAY)
        median = cv2.cvtColor(median, cv2.COLOR_GRAY2BGR)
    median = cv2.resize(median, (BALLTRACK_W, BALLTRACK_H)) / 255.0
    median = np.moveaxis(np.expand_dims(median, 0), -1, 1)

    data = np.concatenate([np.copy(median), np.moveaxis(seq, -1, 1)], 0).reshape(
        -1, BALLTRACK_H, BALLTRACK_W
    )
    return data


def _gray3_median(video: Path, cache_dir: Path) -> Path | None:
    """Median background in GRAY, cached separately from the colour one."""
    import cv2
    import numpy as np

    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / (video.stem + "__median_gray.npz")
    if target.is_file():
        return target
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return None
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()
    if not frames:
        return None
    np.savez_compressed(target, median=np.median(np.stack(frames, 0), axis=0).astype(np.uint8))
    return target


def run_balltrack_gray3(model, device: str) -> list[dict]:
    """Score BallTrack on the 36 manual ball GT frames in both input modes."""
    import numpy as np
    import torch

    entries, _audit = load_manual_ball_gt()
    colour_median_cache = balltrack_root() / "medians"
    gray_median_cache = balltrack_root() / "medians_gray"
    rows: list[dict] = []

    for gt in entries:
        record = {
            "image_id": gt.image_id,
            "session_id": gt.session_id,
            "source_id": gt.source_id,
            "frame_index": gt.frame_index,
            "has_source_video": gt.source_video is not None,
        }
        for mode in ("color", "gray3"):
            if gt.source_video is None:
                record[mode + "_detected"] = False
                record[mode + "_error_px"] = None
                record[mode + "_confidence"] = None
                record[mode + "_center"] = None
                continue
            median_cache = colour_median_cache if mode == "color" else gray_median_cache
            if mode == "color":
                from .ball_bakeoff import compute_clip_median

                median_path = compute_clip_median(gt.source_video, median_cache)
            else:
                median_path = _gray3_median(gt.source_video, median_cache)
            if median_path is None:
                record[mode + "_detected"] = False
                record[mode + "_error_px"] = None
                record[mode + "_confidence"] = None
                record[mode + "_center"] = None
                continue
            data = build_balltrack_input(gt, median_path, mode)
            if data is None:
                record[mode + "_detected"] = False
                record[mode + "_error_px"] = None
                record[mode + "_confidence"] = None
                record[mode + "_center"] = None
                continue
            tensor = torch.from_numpy(np.array([data])).float().to(device)
            with torch.no_grad():
                preds, _, _ = model.forward(frames=tensor)
            heatmap = preds.detach().cpu().numpy()[0][0]
            x, y, w, h, conf = decode_heatmap(heatmap, thre=BALLTRACK_THRE)
            sx = gt.image_width / BALLTRACK_W
            sy = gt.image_height / BALLTRACK_H
            cx = int((x + w / 2) * sx) if (w or h) else 0
            cy = int((y + h / 2) * sy) if (w or h) else 0
            detected = not (cx == 0 and cy == 0)
            sc = score(gt.ball_boxes, [cx, cy] if detected else None, gt.image_width, gt.image_height)
            record[mode + "_detected"] = bool(detected)
            record[mode + "_error_px"] = sc["center_error_px"]
            record[mode + "_confidence"] = round(conf, 4)
            record[mode + "_center"] = [cx, cy] if detected else None
            record[mode + "_heatmap_max"] = float(heatmap.max())
        rows.append(record)
    return rows


def summarize_mode(rows: list[dict], mode: str) -> dict:
    total = len(rows)
    detected = [r for r in rows if r.get(mode + "_detected")]
    errors = [r[mode + "_error_px"] for r in detected if r.get(mode + "_error_px") is not None]
    return {
        "mode": mode,
        "frames": total,
        "detected": len(detected),
        "detection_presence": round(len(detected) / total, 4) if total else None,
        "center_error_median": percentile(errors, 0.5),
        "center_error_p90": percentile(errors, 0.9),
        "center_error_p95": percentile(errors, 0.95),
        "localized_le_50px": sum(1 for e in errors if e <= 50),
    }


def run_yolo_gray3_fallback(weights: Path, base_conf: float, ball_conf: float) -> dict:
    """YOLO ball on the same 36 frames, with the image converted gray -> 3ch."""
    from ultralytics import YOLO

    import numpy as np

    from .ball_bakeoff import yolo_predict_ball

    model = YOLO(str(weights))
    entries, _audit = load_manual_ball_gt()
    rows = []
    for gt in entries:
        image = read_image_robust(gt.image_path)
        if image is None:
            continue
        import cv2

        gray3 = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        # Reuse the production path but feed the gray3 image instead of the colour image.
        gt_gray = BallGt(
            image_id=gt.image_id,
            image_path=gt.image_path,
            session_id=gt.session_id,
            source_id=gt.source_id,
            frame_index=gt.frame_index,
            image_width=gt.image_width,
            image_height=gt.image_height,
            ball_boxes=gt.ball_boxes,
            source_video=gt.source_video,
        )
        results = model.predict(gray3, conf=base_conf, iou=INFER_IOU, imgsz=INFER_IMGSZ, verbose=False)
        boxes = []
        for result in results:
            raw = getattr(result, "boxes", None)
            if raw is None or len(raw) == 0:
                continue
            for xyxy, confidence, class_id in zip(raw.xyxy.tolist(), raw.conf.tolist(), raw.cls.tolist()):
                if int(class_id) != 0:
                    continue
                x1, y1, x2, y2 = (float(v) for v in xyxy)
                boxes.append((float(confidence), [(x1 + x2) / 2, (y1 + y2) / 2]))
        boxes.sort(key=lambda b: -b[0])
        accepted = [b for b in boxes if b[0] >= ball_conf]
        best = accepted[0] if accepted else None
        sc = score(gt.ball_boxes, best[1] if best else None, gt.image_width, gt.image_height)
        rows.append({
            "image_id": gt.image_id,
            "detected": best is not None,
            "confidence": best[0] if best else None,
            "center": best[1] if best else None,
            "error_px": sc["center_error_px"],
        })
    detected = [r for r in rows if r["detected"]]
    errors = [r["error_px"] for r in detected if r["error_px"] is not None]
    return {
        "mode": "yolo_gray3",
        "frames": len(rows),
        "detected": len(detected),
        "detection_presence": round(len(detected) / len(rows), 4) if rows else None,
        "center_error_median": percentile(errors, 0.5),
        "center_error_p90": percentile(errors, 0.9),
        "center_error_p95": percentile(errors, 0.95),
        "localized_le_50px": sum(1 for e in errors if e <= 50),
        "rows": rows,
    }
