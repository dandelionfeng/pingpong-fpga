"""FINAL ball detector bake-off: current YOLO ball vs official RacketVision BallTrack.

公平性设计（务必保持）
----------------------
1. **同一个 GT 集合**：只用 `PATHS.bndstt_manual_gt_dir` 中 review_state=MANUAL_REVIEWED 且
   **有 ball 框** 的图；只读，绝不写入、绝不训练。
2. **BallTrack 用官方模型代码原文**：``official_reference/model/tracknet_v3.py`` 未做任何修改，
   权重加载后逐参数校验；mmengine 只提供 API-compatible shim（不改变任何张量）。
3. **BallTrack 是时序模型**：每个 GT center frame 都在其**原始 source video 的真实连续上下文**中
   推理（seq_len=4），只在 center frame 计分。绝不把孤立单帧硬塞给它。
4. **YOLO 用正式工作点**：base_conf=0.02 推理，ball_conf=0.05 接受；同时记录 0.02~0.05 的候选。
5. **指标**：detection presence、center error(px)、center error normalized（/diagonal），
   报 median/P90/P95。**无足够 negative GT 时不伪造 precision。**

BallTrack 输入契约（来自官方 inference.py，逐条对齐）
----------------------------------------------------
* 帧 resize 到 512x288，/255；
* median 背景 resize 到 512x288，/255，作为一个"帧"放在序列最前；
* 每个样本取 ``seq_len`` 帧（index i-seq_len .. i-1，负数 clip 到 0），
  拼成 ``(3*(seq_len+1), H, W)``；
* 输出 heatmap 经 ``thre``（默认 0.5）二值化 → 最大轮廓外接矩形 → 取矩形内热图均值作为
  confidence；center 乘 (sx, sy) 回到**原图坐标**；
* ``cx==0 and cy==0`` 视为未检测到（Visibility=0）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import INFER_IMGSZ, INFER_IOU, PATHS
from .dataset_qa import read_image_robust
from .yolo_io import Box

# 正式工作点
BASE_CONF = 0.02
BALL_CONF = 0.05
RACKET_CONF = 0.30

BALLTRACK_SEQ_LEN = 4
BALLTRACK_W = 512
BALLTRACK_H = 288
BALLTRACK_THRE = 0.5
BALLTRACK_CONTEXT_BEFORE = 4      # center frame 之前的连续帧数
BALLTRACK_CONTEXT_AFTER = 4       # center frame 之后（BallTrack 只用到 i-1..i-seq_len，多取无妨）

SWITCH_RULE_PP = 0.05             # 部署优先规则：detection presence 差距 < 5pp 时优先 YOLO


def report_dir() -> Path:
    return PATHS.reports_dir / "BALL_DETECTOR_FINAL_BAKEOFF"


def balltrack_root() -> Path:
    return PATHS.repo_root / "artifacts" / "files" / "models" / "balltrack"


def balltrack_checkpoint() -> Path:
    return balltrack_root() / "balltrack_best.pth"


def balltrack_source_dir() -> Path:
    return balltrack_root() / "official_reference"


# ================================================================ GT 集合
@dataclass
class BallGt:
    image_id: str
    image_path: Path
    session_id: str
    source_id: str
    frame_index: int
    image_width: int
    image_height: int
    ball_boxes: list[list[float]]
    source_video: Path | None = None
    source_frame_count: int = 0
    source_fps: float = 0.0


def _frames_manifest() -> dict[str, dict]:
    from .finetune_domain import read_csv_rows

    path = PATHS.bndstt_frames_manifest
    if not path.is_file():
        return {}
    rows = read_csv_rows(path)
    out: dict[str, dict] = {}
    for row in rows:
        image_id = row.get("image_id", "").strip()
        if not image_id:
            rel = row.get("original_image_path", "")
            image_id = Path(rel).stem if rel else ""
        if image_id:
            out[image_id] = row
    return out


def load_manual_ball_gt() -> tuple[list[BallGt], dict]:
    """只读加载人工确认且有 ball 框的 GT（审计结果一并返回）。"""
    gt_dir = PATHS.bndstt_manual_gt_dir / "annotations_json"
    if not gt_dir.is_dir():
        return [], {"available": False, "reason": "annotations_json missing"}
    manifest = _frames_manifest()
    mvp = PATHS.bndstt_mvp_dir
    entries: list[BallGt] = []
    audit = {
        "annotation_files": 0,
        "review_states": {},
        "with_ball": 0,
        "without_ball": 0,
        "ball_instances": 0,
        "abnormal_ball_boxes": 0,
        "missing_source_video": 0,
    }
    for path in sorted(gt_dir.glob("*.json")):
        audit["annotation_files"] += 1
        payload = json.loads(path.read_text(encoding="utf-8"))
        state = payload.get("review_state", "?")
        audit["review_states"][state] = audit["review_states"].get(state, 0) + 1
        balls = []
        for obj in payload.get("objects", []):
            if str(obj.get("class_name", "")).lower() != "ball":
                continue
            box = obj.get("bbox_xyxy")
            if not box or len(box) != 4:
                audit["abnormal_ball_boxes"] += 1
                continue
            x1, y1, x2, y2 = (float(v) for v in box)
            if x2 <= x1 or y2 <= y1 or not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
                audit["abnormal_ball_boxes"] += 1
                continue
            balls.append([x1, y1, x2, y2])
        if not balls:
            audit["without_ball"] += 1
            continue
        audit["with_ball"] += 1
        audit["ball_instances"] += len(balls)
        image_id = payload["image_id"]
        row = manifest.get(image_id, {})
        source_video = None
        rel = row.get("source_video_path", "")
        if rel:
            # frames_manifest 里的相对路径以 BNDSTT/ 为根，而不是 BNDSTT_MVP_v1/。
            # 两处都找，避免再次误判为“没有视频”。
            bndstt_root = mvp.parent / "BNDSTT"
            for base in (bndstt_root, mvp):
                candidate = base / rel
                if candidate.is_file():
                    source_video = candidate
                    break
        if source_video is None:
            audit["missing_source_video"] += 1
        entries.append(
            BallGt(
                image_id=image_id,
                image_path=mvp / payload["image_path"],
                session_id=payload.get("session_id", ""),
                source_id=payload.get("source_id", ""),
                frame_index=int(payload.get("frame_index", 0)),
                image_width=int(payload.get("image_width", 1920)),
                image_height=int(payload.get("image_height", 1080)),
                ball_boxes=balls,
                source_video=source_video,
            )
        )
    audit["usable_center_frames"] = len(entries)
    audit["with_source_video"] = sum(1 for e in entries if e.source_video is not None)
    return entries, audit


# ================================================================ BallTrack
def _extract_video_frames(video: Path, indices: list[int]) -> dict[int, "object"]:
    import cv2

    wanted = sorted(set(i for i in indices if i >= 0))
    out: dict[int, object] = {}
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return out
    current = 0
    target = set(wanted)
    max_index = max(target) if target else -1
    while current <= max_index:
        ok, frame = cap.read()
        if not ok:
            break
        if current in target:
            out[current] = frame
        current += 1
    cap.release()
    return out


def compute_clip_median(video: Path, cache_dir: Path) -> Path | None:
    """按官方 create_median.py 语义：对 source video 全部帧取逐像素中位数。"""
    import cv2
    import numpy as np

    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / (video.stem + "__median.npz")
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
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()
    if not frames:
        return None
    median = np.median(np.stack(frames, 0), axis=0).astype(np.uint8)
    np.savez_compressed(target, median=median)
    return target


def build_balltrack_inferencer():
    """构建官方 BallTrack 推理器（官方模型代码原文 + mmengine shim）。"""
    import torch

    src = balltrack_source_dir()
    shim = src / "mmengine_shim"
    for entry in (str(shim), str(src)):
        if entry not in sys.path:
            sys.path.insert(0, entry)

    ckpt = balltrack_checkpoint()
    if not ckpt.is_file():
        raise FileNotFoundError("BallTrack checkpoint missing: " + str(ckpt))

    from model import tracknet_v3  # noqa: F401  (official code, unmodified)

    model = tracknet_v3.TrackNet(
        in_dim=3 * (BALLTRACK_SEQ_LEN + 1),
        out_dim=BALLTRACK_SEQ_LEN,
        mixup=False,
        alpha=0.5,
        last_only=True,
    )
    state = torch.load(str(ckpt), map_location="cpu", weights_only=False)
    state = state.get("state_dict", state) if isinstance(state, dict) else state
    if isinstance(state, dict) and isinstance(state.get("model"), dict):
        state = state["model"]
    state = {(k[7:] if k.startswith("module.") else k): v for k, v in state.items()}
    missing, unexpected = model.load_state_dict(state, strict=False)
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    return model, device, {"missing_keys": list(missing), "unexpected_keys": list(unexpected)}


def decode_heatmap(heatmap, thre: float = BALLTRACK_THRE):
    """官方 _predict_location：阈值 → 最大轮廓外接矩形 → 矩形内均值作为 confidence。"""
    import cv2
    import numpy as np

    mask = heatmap > thre
    if mask.max() == 0:
        return 0, 0, 0, 0, 0.0
    mask_img = (mask.astype("uint8")) * 255
    contours, _ = cv2.findContours(mask_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0, 0, 0, 0, 0.0
    rects = [cv2.boundingRect(c) for c in contours]
    x, y, w, h = max(rects, key=lambda r: r[2] * r[3])
    conf = float(np.mean(heatmap[y:y + h, x:x + w]))
    return x, y, w, h, conf


def balltrack_predict_center(
    model, device, gt: BallGt, median_path: Path, context_before: int = BALLTRACK_CONTEXT_BEFORE,
    context_after: int = BALLTRACK_CONTEXT_AFTER, thre: float = BALLTRACK_THRE, timing: dict | None = None,
) -> dict:
    """在真实连续上下文里推理，只返回 center frame 的预测（原图坐标）。"""
    import cv2
    import numpy as np
    import torch

    if gt.source_video is None:
        return {"ok": False, "reason": "no source video", "detected": False}

    center = gt.frame_index
    indices = list(range(center - context_before, center + context_after + 1))
    frames_by_index = _extract_video_frames(gt.source_video, indices)
    if center not in frames_by_index:
        return {"ok": False, "reason": "center frame not extractable", "detected": False}

    seq_indices = [center - BALLTRACK_SEQ_LEN + k for k in range(BALLTRACK_SEQ_LEN)]
    seq_indices = [max(0, i) for i in seq_indices]
    resolved = []
    for i in seq_indices:
        if i in frames_by_index:
            resolved.append(frames_by_index[i])
        else:
            nearest = min(frames_by_index, key=lambda k: abs(k - i))
            resolved.append(frames_by_index[nearest])
    seq = np.array([cv2.resize(f, (BALLTRACK_W, BALLTRACK_H)) for f in resolved],
                   dtype=np.float32) / 255.0

    median = np.load(median_path)["median"]
    median = cv2.resize(median, (BALLTRACK_W, BALLTRACK_H)) / 255.0
    median = np.moveaxis(np.expand_dims(median, 0), -1, 1)

    data = np.concatenate([np.copy(median), np.moveaxis(seq, -1, 1)], 0).reshape(
        -1, BALLTRACK_H, BALLTRACK_W
    )
    tensor = torch.from_numpy(np.array([data])).float().to(device)

    started = time.perf_counter()
    with torch.no_grad():
        preds, _, _ = model.forward(frames=tensor)
    elapsed = (time.perf_counter() - started) * 1000.0
    if timing is not None:
        timing.setdefault("balltrack_ms", []).append(elapsed)

    heatmap = preds.detach().cpu().numpy()[0][0]
    x, y, w, h, conf = decode_heatmap(heatmap, thre=thre)
    sx = gt.image_width / BALLTRACK_W
    sy = gt.image_height / BALLTRACK_H
    cx = int((x + w / 2) * sx) if (w or h) else 0
    cy = int((y + h / 2) * sy) if (w or h) else 0
    detected = not (cx == 0 and cy == 0)
    return {
        "ok": True,
        "detected": bool(detected),
        "center_xy": [cx, cy],
        "confidence": round(conf, 4),
        "heatmap_max": float(heatmap.max()),
        "visibility": 1 if detected else 0,
        "context_indices": indices,
        "seq_indices": seq_indices,
    }


# ================================================================ YOLO ball
def yolo_predict_ball(model, gt: BallGt, conf: float = BASE_CONF, timing: dict | None = None) -> dict:
    """正式工作点：base_conf 推理，记录 ball_conf 接受与否。"""
    import numpy as np

    image = read_image_robust(gt.image_path)
    if image is None:
        return {"ok": False, "reason": "cannot read image", "detected": False}
    started = time.perf_counter()
    results = model.predict(image, conf=conf, iou=INFER_IOU, imgsz=INFER_IMGSZ, verbose=False)
    elapsed = (time.perf_counter() - started) * 1000.0
    if timing is not None:
        timing.setdefault("yolo_ms", []).append(elapsed)

    boxes: list[dict] = []
    for result in results:
        raw = getattr(result, "boxes", None)
        if raw is None or len(raw) == 0:
            continue
        for xyxy, confidence, class_id in zip(raw.xyxy.tolist(), raw.conf.tolist(), raw.cls.tolist()):
            if int(class_id) != 0:
                continue
            x1, y1, x2, y2 = (float(v) for v in xyxy)
            boxes.append({
                "confidence": round(float(confidence), 6),
                "bbox_xyxy": [round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)],
                "center_xy": [round((x1 + x2) / 2, 3), round((y1 + y2) / 2, 3)],
            })
    boxes.sort(key=lambda b: -b["confidence"])
    accepted = [b for b in boxes if b["confidence"] >= BALL_CONF]
    below = [b for b in boxes if b["confidence"] < BALL_CONF]
    best = accepted[0] if accepted else None
    return {
        "ok": True,
        "detected": best is not None,
        "center_xy": best["center_xy"] if best else None,
        "confidence": best["confidence"] if best else None,
        "bbox_xyxy": best["bbox_xyxy"] if best else None,
        "accepted_count": len(accepted),
        "below_ball_conf_count": len(below),
        "all_confidences": [b["confidence"] for b in boxes],
        "_image": image,
    }


# ================================================================ 计分
def score(gts: list[list[float]], prediction_center: list[float] | None, width: int, height: int) -> dict:
    """center error vs 最近的 GT ball 框中心（px 与 归一化）。"""
    if prediction_center is None:
        return {"center_error_px": None, "center_error_norm": None}
    best = None
    for box in gts:
        gx = (box[0] + box[2]) / 2.0
        gy = (box[1] + box[3]) / 2.0
        distance = math.hypot(prediction_center[0] - gx, prediction_center[1] - gy)
        if best is None or distance < best:
            best = distance
    diagonal = math.hypot(width, height)
    return {
        "center_error_px": round(best, 3) if best is not None else None,
        "center_error_norm": round(best / diagonal, 6) if best is not None else None,
    }


def percentile(values: list[float], fraction: float):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def summarize(rows: list[dict], method: str) -> dict:
    detections = [r for r in rows if r["method"] == method]
    if not detections:
        return {"method": method, "evaluated": 0}
    present = [r for r in detections if r["detected"]]
    errors = [r["center_error_px"] for r in present if r["center_error_px"] is not None]
    norms = [r["center_error_norm"] for r in present if r["center_error_norm"] is not None]
    confs = [r["confidence"] for r in present if r.get("confidence") is not None]
    return {
        "method": method,
        "evaluated": len(detections),
        "detection_presence": round(len(present) / len(detections), 4),
        "detection_presence_frames": len(present),
        "center_error_px_median": percentile(errors, 0.5),
        "center_error_px_p90": percentile(errors, 0.9),
        "center_error_px_p95": percentile(errors, 0.95),
        "center_error_px_mean": round(sum(errors) / len(errors), 3) if errors else None,
        "center_error_norm_median": percentile(norms, 0.5),
        "center_error_norm_p90": percentile(norms, 0.9),
        "center_error_norm_p95": percentile(norms, 0.95),
        "confidence_median": percentile(confs, 0.5),
        "note": "detection presence is NOT recall; this GT set has no verified negative frames",
    }
