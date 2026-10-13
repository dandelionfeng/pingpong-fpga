"""连续视频 temporal diagnostic（PART B）。

**没有 GT，因此这里不产出任何精度指标。** 只统计结构性指标：
candidate coverage、dropout、continuity、track break 等。

三个状态严格区分（方案第 25/27 条）
-----------------------------------
* ``DETECTED``          : 当前帧有 detector candidate，conf >= 工作阈值，且与 track 匹配；
* ``RECOVERED_LOW_CONF``: 当前帧**确实存在** detector candidate，其 conf 低于工作阈值但 >= base_conf，
                          且满足运动 gate，被 track 接受；
* ``PREDICTED_ONLY``    : 当前帧**完全没有** detector candidate，只有 Kalman 预测。

``PREDICTED_ONLY`` **不算**检测到球，也**不算** recovery。

因果性（方案第 40/41 条）
-------------------------
* ``causal`` 版本只使用 t, t-1, t-2 …，**不访问未来帧**，算法延迟 0 帧；
* ``centered`` 版本使用 t±k，仅作 **offline diagnostic**，其算法延迟为 k 帧，
  报告中按 60 fps 折算成毫秒。
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import INFER_IMGSZ, INFER_IOU, PATHS
from .finetune_eval import predict_boxes
from .temporal_benchmark import frames_dir, load_manifest

CLASS_BALL, CLASS_RACKET = 0, 1
CLASS_NAMES = {0: "ball", 1: "racket"}

# 状态常量
DETECTED = "DETECTED"
RECOVERED = "RECOVERED_LOW_CONF"
PREDICTED_ONLY = "PREDICTED_ONLY"
NONE = "NONE"

STABLE_SEGMENT_MIN_FRAMES = 5
ISOLATED_NEIGHBOR_RADIUS = 2


def report_dir() -> Path:
    return PATHS.reports_dir / "TEMPORAL_DIAGNOSTIC_V1"


def clips_dir() -> Path:
    return report_dir() / "clips"


# ================================================================ RAW 候选
def _clip_float(clip: dict, key: str, default: float = 0.0) -> float:
    """manifest 从 CSV 读出，数值字段是字符串；统一转 float。"""
    try:
        return float(clip.get(key, default))
    except (TypeError, ValueError):
        return default


def extract_raw_candidates(clip: dict, weights: Path, base_conf: float, device: str | int = 0) -> dict:
    """逐帧低阈值推理，缓存**真正相邻**帧的全部候选。"""
    from ultralytics import YOLO

    from .dataset_qa import read_image_robust

    model = YOLO(str(weights))
    clip_frames = frames_dir() / clip["clip_id"]
    paths = sorted(clip_frames.glob("f*.jpg"))
    fps = _clip_float(clip, "fps", 60.0)
    frames: list[dict] = []
    for index, path in enumerate(paths):
        image = read_image_robust(path)
        if image is None:
            continue
        preds = predict_boxes(model, image, conf=base_conf, imgsz=INFER_IMGSZ,
                              iou=INFER_IOU, device=device)
        height, width = image.shape[:2]
        frames.append(
            {
                "frame_idx": index,
                "timestamp": round(index / fps, 6) if fps else None,
                "width": width,
                "height": height,
                "candidates": [
                    {
                        "class_id": int(p.class_id),
                        "confidence": round(float(p.confidence), 6),
                        "bbox_xyxy": [round(v, 3) for v in p.to_xyxy()],
                        "center_xy": [round((p.x1 + p.x2) / 2, 3), round((p.y1 + p.y2) / 2, 3)],
                    }
                    for p in preds
                    if p.class_id in CLASS_NAMES
                ],
            }
        )
    return {
        "clip_id": clip["clip_id"],
        "session_id": clip["session_id"],
        "source_id": clip["source_id"],
        "fps": fps,
        "frames": frames,
        "base_conf": base_conf,
        "weights": str(weights),
    }


# ================================================================ 几何工具
def norm_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """center distance / image diagonal（对分辨率不敏感）。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def diagonal(width: int, height: int) -> float:
    return math.hypot(width, height)


def size_ratio(a: list[float], b: list[float]) -> float:
    wa, ha = a[2] - a[0], a[3] - a[1]
    wb, hb = b[2] - b[0], b[3] - b[1]
    aa, ab = max(1e-6, wa * ha), max(1e-6, wb * hb)
    return max(aa, ab) / min(aa, ab)


# ================================================================ 关联器
@dataclass
class TrackerConfig:
    ball_conf: float = 0.10
    racket_conf: float = 0.25
    base_conf: float = 0.02
    max_prediction_gap: int = 2
    ball_gate_norm: float = 0.06      # center distance / diagonal
    racket_gate_norm: float = 0.05
    racket_gate_iou: float = 0.10
    ball_size_ratio_max: float = 4.0
    init_conf_ratio: float = 1.0      # 初始化 track 需要 conf >= working threshold * ratio
    smoothing: str = "causal"         # causal | centered
    smoothing_window: int = 3


def working_conf(config: TrackerConfig, class_id: int) -> float:
    return config.ball_conf if class_id == CLASS_BALL else config.racket_conf


def is_isolated(frame_index: int, center: tuple[float, float], frames: list[dict],
                class_id: int, config: TrackerConfig, width: int, height: int) -> bool:
    """前后 ``ISOLATED_NEIGHBOR_RADIUS`` 帧内都没有 spatially compatible 候选。"""
    diag = diagonal(width, height)
    gate = config.ball_gate_norm if class_id == CLASS_BALL else config.racket_gate_norm
    for offset in range(-ISOLATED_NEIGHBOR_RADIUS, ISOLATED_NEIGHBOR_RADIUS + 1):
        if offset == 0:
            continue
        index = frame_index + offset
        if index < 0 or index >= len(frames):
            continue
        for candidate in frames[index]["candidates"]:
            if candidate["class_id"] != class_id:
                continue
            if norm_distance(center, tuple(candidate["center_xy"])) / diag <= gate:
                return False
    return True


class SimpleTracker:
    """极简 tracking-by-detection：只做 spatial gating + 因果置信度平滑。

    不做 Kalman 预测，因此没有 PREDICTED_ONLY。
    """

    def __init__(self, class_id: int, config: TrackerConfig):
        self.class_id = class_id
        self.config = config
        self.track_id = 0
        self.center: tuple[float, float] | None = None
        self.velocity: tuple[float, float] = (0.0, 0.0)
        self.conf_history: list[float] = []
        self.last_bbox: list[float] | None = None
        self.states: list[str] = []

    def gate(self, frame: dict, candidate: dict) -> bool:
        if self.center is None:
            return True
        diag = diagonal(frame["width"], frame["height"])
        predicted = (
            self.center[0] + self.velocity[0],
            self.center[1] + self.velocity[1],
        )
        gate = (
            self.config.ball_gate_norm
            if self.class_id == CLASS_BALL
            else self.config.racket_gate_norm
        )
        return norm_distance(predicted, tuple(candidate["center_xy"])) / diag <= gate

    def smoothed_confidence(self, candidate_conf: float) -> float:
        """因果平滑：只用 t, t-1, t-2 …（不含未来帧）。"""
        window = max(1, self.config.smoothing_window)
        history = (self.conf_history + [candidate_conf])[-window:]
        weights = list(range(1, len(history) + 1))
        total = sum(weights)
        return sum(h * w for h, w in zip(history, weights)) / total if total else candidate_conf

    def update(self, frame: dict, candidate: dict | None) -> tuple[str, float | None]:
        working = working_conf(self.config, self.class_id)
        if candidate is None:
            self.states.append(NONE)
            return NONE, None
        smoothed = self.smoothed_confidence(candidate["confidence"])
        accepted = smoothed >= working
        if accepted:
            state = DETECTED if candidate["confidence"] >= working else RECOVERED
        else:
            state = NONE
        if accepted:
            center = tuple(candidate["center_xy"])
            if self.center is not None:
                self.velocity = (center[0] - self.center[0], center[1] - self.center[1])
            self.center = center
            self.last_bbox = candidate["bbox_xyxy"]
        self.conf_history.append(candidate["confidence"])
        self.states.append(state)
        return state, smoothed


def run_simple(frames: list[dict], config: TrackerConfig) -> dict:
    """对 ball 跑 SIMPLE（racket 只做 basic association，不细调）。"""
    tracker = SimpleTracker(CLASS_BALL, config)
    per_frame: list[dict] = []
    for frame in frames:
        candidates = [c for c in frame["candidates"] if c["class_id"] == CLASS_BALL]
        best = None
        for candidate in sorted(candidates, key=lambda c: -c["confidence"]):
            if tracker.gate(frame, candidate):
                best = candidate
                break
        state, smoothed = tracker.update(frame, best)
        per_frame.append(
            {
                "frame_idx": frame["frame_idx"],
                "state": state,
                "raw_conf": None if best is None else best["confidence"],
                "smoothed_conf": None if smoothed is None else round(smoothed, 6),
                "center_xy": None if best is None else best["center_xy"],
                "bbox_xyxy": None if best is None else best["bbox_xyxy"],
                "cached_candidate_present": bool(candidates),
                "accepted_candidate": state in (DETECTED, RECOVERED),
            }
        )
    return {"tracker": "SIMPLE", "per_frame": per_frame}


# ================================================================ Kalman
class KalmanTracker:
    """常速度 Kalman（状态 x, y, vx, vy），允许短时 dropout 用预测维持。"""

    def __init__(self, class_id: int, config: TrackerConfig, initial_center, dt: float = 1.0):
        self.class_id = class_id
        self.config = config
        self.dt = dt
        self.gap = 0
        self.reinitializations = 0
        self.initialized = False
        # 状态与协方差（4x4）
        self.x = [initial_center[0], initial_center[1], 0.0, 0.0]
        self.P = [[100.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        self.process_noise = 0.5
        self.measurement_noise = 4.0

    # --- 线性代数（避免引入 numpy 依赖之外的复杂度） -------------
    def _predict(self) -> None:
        dt = self.dt
        F = [
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ]
        x_new = [
            F[i][0] * self.x[0] + F[i][1] * self.x[1] + F[i][2] * self.x[2] + F[i][3] * self.x[3]
            for i in range(4)
        ]
        P_new = [[0.0] * 4 for _ in range(4)]
        FP = [[sum(F[i][k] * self.P[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
        P_new = [[sum(FP[i][k] * F[j][k] for k in range(4)) for j in range(4)] for i in range(4)]
        q = self.process_noise
        for i in range(4):
            P_new[i][i] += q * (10.0 if i >= 2 else 1.0)
        self.x, self.P = x_new, P_new

    def _update(self, measurement) -> None:
        H = [[1, 0, 0, 0], [0, 1, 0, 0]]
        y = [measurement[0] - self.x[0], measurement[1] - self.x[1]]
        PHt = [[sum(self.P[i][k] * H[j][k] for k in range(4)) for j in range(2)] for i in range(4)]
        S = [[sum(H[i][k] * PHt[k][j] for k in range(4)) + (self.measurement_noise if i == j else 0.0)
              for j in range(2)] for i in range(2)]
        det = S[0][0] * S[1][1] - S[0][1] * S[1][0]
        if abs(det) < 1e-12:
            return
        Sinv = [[S[1][1] / det, -S[0][1] / det], [-S[1][0] / det, S[0][0] / det]]
        K = [[sum(PHt[i][k] * Sinv[k][j] for k in range(2)) for j in range(2)] for i in range(4)]
        for i in range(4):
            self.x[i] += K[i][0] * y[0] + K[i][1] * y[1]
        KH = [[sum(K[i][k] * H[k][j] for k in range(2)) for j in range(4)] for i in range(4)]
        IminusKH = [[(1.0 if i == j else 0.0) - KH[i][j] for j in range(4)] for i in range(4)]
        self.P = [[sum(IminusKH[i][k] * self.P[k][j] for k in range(4)) for j in range(4)]
                  for i in range(4)]

    def predict(self) -> tuple[float, float]:
        self._predict()
        return (self.x[0], self.x[1])

    def update(self, measurement) -> None:
        self._update(measurement)
        self.gap = 0

    def gate_ok(self, frame: dict, candidate: dict, strict: bool = False) -> bool:
        diag = diagonal(frame["width"], frame["height"])
        gate = (
            self.config.ball_gate_norm if self.class_id == CLASS_BALL
            else self.config.racket_gate_norm
        )
        if strict and self.class_id == CLASS_RACKET:
            gate = min(gate, self.config.racket_gate_norm)
        if norm_distance((self.x[0], self.x[1]), tuple(candidate["center_xy"])) / diag > gate:
            return False
        return True


def run_kalman(frames: list[dict], config: TrackerConfig) -> dict:
    """Kalman tracking-by-detection：严格区分三种状态。"""
    working = working_conf(config, CLASS_BALL)
    tracker: KalmanTracker | None = None
    per_frame: list[dict] = []
    track_segments: list[int] = []
    current_segment = 0
    reinit = 0
    supported = 0

    for frame in frames:
        candidates = sorted(
            [c for c in frame["candidates"] if c["class_id"] == CLASS_BALL],
            key=lambda c: -c["confidence"],
        )
        state = NONE
        shown_conf = None
        center = None
        bbox = None
        accepted = False

        if tracker is None:
            # 初始化需要 conf >= working
            init = next((c for c in candidates if c["confidence"] >= working), None)
            if init is not None:
                tracker = KalmanTracker(CLASS_BALL, config, tuple(init["center_xy"]))
                tracker.initialized = True
                tracker.update(tuple(init["center_xy"]))
                state = DETECTED
                shown_conf = init["confidence"]
                center, bbox = init["center_xy"], init["bbox_xyxy"]
                accepted = True
                current_segment = 1
        else:
            predicted = tracker.predict()
            matched = None
            for candidate in candidates:
                if tracker.gate_ok(frame, candidate):
                    matched = candidate
                    break
            if matched is not None:
                tracker.update(tuple(matched["center_xy"]))
                if matched["confidence"] >= working:
                    state = DETECTED
                else:
                    # 真实存在 candidate、低于工作阈值、但被 gate 接受 → recovery
                    state = RECOVERED
                shown_conf = matched["confidence"]
                center, bbox = matched["center_xy"], matched["bbox_xyxy"]
                accepted = True
                current_segment += 1
            else:
                tracker.gap += 1
                if tracker.gap <= config.max_prediction_gap:
                    state = PREDICTED_ONLY
                    center = [round(predicted[0], 3), round(predicted[1], 3)]
                    current_segment += 1
                else:
                    # 超过最大预测间隔：track 断开并重新初始化
                    track_segments.append(current_segment)
                    current_segment = 0
                    tracker = None
                    reinit += 1
        if state in (DETECTED, RECOVERED):
            supported += 1
        per_frame.append(
            {
                "frame_idx": frame["frame_idx"],
                "state": state,
                "raw_conf": shown_conf,
                "center_xy": center,
                "bbox_xyxy": bbox,
                # 语义区分（关键）：
                #   cached_candidate_present : 本帧缓存中是否存在 ball 候选（RAW 层事实）
                #   accepted_candidate       : track 是否接受了某个候选（DETECTED/RECOVERED 的条件）
                "cached_candidate_present": bool(candidates),
                "accepted_candidate": accepted,
                "candidates_below_threshold": sum(
                    1 for c in candidates if c["confidence"] < working
                ),
            }
        )
    if current_segment:
        track_segments.append(current_segment)
    return {
        "tracker": "KALMAN",
        "per_frame": per_frame,
        "track_segments": track_segments,
        "reinitializations": reinit,
        "detector_supported_frames": supported,
    }


# ================================================================ 指标
def summarize_clip(frames: list[dict], per_frame: list[dict], config: TrackerConfig,
                   tracker_name: str) -> dict:
    total = len(per_frame)
    states = [row["state"] for row in per_frame]
    detected = states.count(DETECTED)
    recovered = states.count(RECOVERED)
    predicted = states.count(PREDICTED_ONLY)
    supported = detected + recovered

    # candidate coverage（RAW 层）
    raw_frames = sum(1 for row in per_frame if row["cached_candidate_present"])
    dropouts: list[int] = []
    run = 0
    for row in per_frame:
        if row["cached_candidate_present"]:
            if run:
                dropouts.append(run)
                run = 0
        else:
            run += 1
    if run:
        dropouts.append(run)

    # track 连续性（仅 trackers）
    # supported_segments 只看 DETECTED / RECOVERED_LOW_CONF，
    # 因为 stable_track_ratio 的分母正是 detector-supported 帧数，
    # 把 PREDICTED_ONLY 计入 segment 会让比值 > 1（无意义）。
    supported_segments: list[int] = []
    all_segments: list[int] = []
    current_supported = 0
    current_all = 0
    for state in states:
        if tracker_name == "RAW":
            continue
        if state in (DETECTED, RECOVERED):
            current_supported += 1
        else:
            if current_supported:
                supported_segments.append(current_supported)
            current_supported = 0
        if state in (DETECTED, RECOVERED, PREDICTED_ONLY):
            current_all += 1
        else:
            if current_all:
                all_segments.append(current_all)
            current_all = 0
    if current_supported:
        supported_segments.append(current_supported)
    if current_all:
        all_segments.append(current_all)
    segments = all_segments
    stable = [s for s in supported_segments if s >= STABLE_SEGMENT_MIN_FRAMES]

    # isolated candidates（ball）
    isolated_total = 0
    isolated_accepted = 0
    for index, frame in enumerate(frames):
        for candidate in frame["candidates"]:
            if candidate["class_id"] != CLASS_BALL:
                continue
            if is_isolated(index, tuple(candidate["center_xy"]), frames, CLASS_BALL,
                           config, frame["width"], frame["height"]):
                isolated_total += 1
                state = per_frame[index]["state"] if index < len(per_frame) else NONE
                if state in (DETECTED, RECOVERED):
                    isolated_accepted += 1

    # center / velocity jump
    centers = [
        row["center_xy"]
        for row in per_frame
        if row["center_xy"] and row["state"] in (DETECTED, RECOVERED)
    ]
    jumps: list[float] = []
    for a, b in zip(centers, centers[1:]):
        diag = diagonal(frames[0]["width"], frames[0]["height"])
        jumps.append(math.hypot(b[0] - a[0], b[1] - a[1]) / diag)
    jumps.sort()

    def pct(values: list[float], fraction: float):
        if not values:
            return None
        index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
        return round(values[index], 6)

    return {
        "tracker": tracker_name,
        "total_frames": total,
        "raw_candidate_coverage": round(raw_frames / total, 4) if total else None,
        "detector_supported_coverage": round(supported / total, 4) if total else None,
        "detected_frames": detected,
        "recovered_low_conf_frames": recovered,
        "predicted_only_frames": predicted,
        "candidate_dropout_count": len(dropouts),
        "longest_candidate_dropout": max(dropouts) if dropouts else 0,
        "candidate_dropout_frames_total": sum(dropouts),
        "track_break_count": max(0, len(segments) - 1),
        "mean_track_segment_length": round(sum(segments) / len(segments), 3) if segments else 0.0,
        "median_track_segment_length": (
            sorted(segments)[len(segments) // 2] if segments else 0
        ),
        "longest_track_segment": max(segments) if segments else 0,
        "stable_track_ratio": (
            round(sum(stable) / supported, 4) if supported else None
        ),
        "stable_track_ratio_definition": (
            "sum(length of every maximal run of >= " + str(STABLE_SEGMENT_MIN_FRAMES)
            + " consecutive DETECTED-or-RECOVERED_LOW_CONF frames) / detector_supported_frames; "
            "PREDICTED_ONLY frames are excluded from both numerator and denominator, "
            "so the ratio is always <= 1"
        ),
        "isolated_candidates_raw": isolated_total,
        "isolated_candidates_accepted": isolated_accepted,
        "center_jump_normalized_median": pct(jumps, 0.5),
        "center_jump_normalized_p95": pct(jumps, 0.95),
        "multi_candidate_frames": sum(
            1 for f in frames if sum(1 for c in f["candidates"] if c["class_id"] == CLASS_BALL) > 1
        ),
    }


def summarize_raw(frames: list[dict]) -> dict:
    """RAW 层（无 track）只统计 candidate coverage / dropout / isolated。

    没有 track，因此所有 track 相关指标为 None；也不产出任何精度类指标。
    """
    config = TrackerConfig()
    total = len(frames)
    present = [any(c["class_id"] == CLASS_BALL for c in f["candidates"]) for f in frames]
    raw_frames = sum(1 for p in present if p)

    dropouts: list[int] = []
    run = 0
    for flag in present:
        if flag:
            if run:
                dropouts.append(run)
                run = 0
        else:
            run += 1
    if run:
        dropouts.append(run)

    isolated_total = 0
    for index, frame in enumerate(frames):
        for candidate in frame["candidates"]:
            if candidate["class_id"] != CLASS_BALL:
                continue
            if is_isolated(index, tuple(candidate["center_xy"]), frames, CLASS_BALL,
                           config, frame["width"], frame["height"]):
                isolated_total += 1

    return {
        "tracker": "RAW",
        "total_frames": total,
        "raw_candidate_coverage": round(raw_frames / total, 4) if total else None,
        "detector_supported_coverage": None,
        "detected_frames": None,
        "recovered_low_conf_frames": None,
        "predicted_only_frames": None,
        "candidate_dropout_count": len(dropouts),
        "longest_candidate_dropout": max(dropouts) if dropouts else 0,
        "track_break_count": None,
        "mean_track_segment_length": None,
        "median_track_segment_length": None,
        "longest_track_segment": None,
        "stable_track_ratio": None,
        "stable_track_ratio_definition": "not applicable to RAW (no tracks)",
        "isolated_candidates_raw": isolated_total,
        "isolated_candidates_accepted": None,
        "multi_candidate_frames": sum(
            1 for f in frames if sum(1 for c in f["candidates"] if c["class_id"] == CLASS_BALL) > 1
        ),
        "center_jump_normalized_median": None,
        "center_jump_normalized_p95": None,
        "candidate_frames": raw_frames,
    }
