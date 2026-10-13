"""检测器 A：YOLOv8n，仅 ball + racket 两类。

对外只暴露原图坐标的 :class:`BallRacketDetection`，并组合成
:class:`PerceptionResultV2`。**不修改** 旧 ``DetectionResult``（ball/hand/racket）
的任何结构，旧模块继续可编译、可运行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import CLASS_BALL, CLASS_NAMES, CLASS_RACKET, SCHEMA_VERSION
from .config import INFER_CONF_DISPLAY, INFER_CONF_REPORT, INFER_IMGSZ, INFER_IOU, PATHS
from .yolo_io import Box, yolo_norm_to_pixel


class DetectionError(RuntimeError):
    """检测结果违反坐标契约（例如框不在原图内）。"""


@dataclass(frozen=True)
class BallRacketDetection:
    """单个检测框（原图像素 xyxy）。"""

    class_id: int
    class_name: str
    confidence: float
    box: Box

    def to_dict(self) -> dict:
        return {
            "class_id": int(self.class_id),
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 6),
            "bbox_xyxy": [round(v, 3) for v in self.box.to_xyxy()],
        }


@dataclass
class PosePersonLite:
    """轻量 person 占位类型，避免 ``ball_racket`` 依赖 torch。

    实际的 pose 数据由 :mod:`wrist_pose` 填充；这里只声明 V2 结果的结构。
    """

    person_id: int
    bbox_xyxy: list[float]
    confidence: float
    left_wrist: dict | None = None
    right_wrist: dict | None = None

    def to_dict(self) -> dict:
        return {
            "person_id": int(self.person_id),
            "bbox_xyxy": [round(float(v), 3) for v in self.bbox_xyxy],
            "confidence": round(float(self.confidence), 6),
            "left_wrist": self.left_wrist,
            "right_wrist": self.right_wrist,
        }


@dataclass
class PerceptionResultV2:
    """C 端感知 V2 的独立结果结构（不替换旧的 DetectionResult）。

    字段
    ----
    ball_racket_detections
        检测器 A 输出，全部为原图坐标。
    pose_persons
        检测器 B 输出，每人含 person bbox 与左右手腕 **关键点**（不是 hand bbox）。
    wrists
        扁平化的手腕列表，便于融合/时序处理。
    association
        HEURISTIC 候选关联结果（可以是 UNKNOWN），由 :mod:`fusion` 填充。
    """

    image_path: str
    image_width: int
    image_height: int
    ball_racket_detections: list[BallRacketDetection] = field(default_factory=list)
    pose_persons: list[PosePersonLite] = field(default_factory=list)
    wrists: list[dict] = field(default_factory=list)
    association: dict | None = None
    schema_version: str = SCHEMA_VERSION

    # --- 查询辅助 ------------------------------------------------------
    def by_class(self, class_id: int) -> list[BallRacketDetection]:
        return [d for d in self.ball_racket_detections if d.class_id == class_id]

    @property
    def balls(self) -> list[BallRacketDetection]:
        return self.by_class(CLASS_BALL)

    @property
    def rackets(self) -> list[BallRacketDetection]:
        return self.by_class(CLASS_RACKET)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "image_path": self.image_path,
            "image_width": int(self.image_width),
            "image_height": int(self.image_height),
            "ball_racket_detections": [d.to_dict() for d in self.ball_racket_detections],
            "pose_persons": [p.to_dict() for p in self.pose_persons],
            "wrists": self.wrists,
            "association": self.association,
        }


def model_class_names(model) -> dict[int, str]:
    """从已加载模型安全读取 ``{class_id: class_name}``。"""
    raw = getattr(model, "names", None)
    if isinstance(raw, dict):
        return {int(k): str(v) for k, v in raw.items()}
    if isinstance(raw, (list, tuple)):
        return {i: str(v) for i, v in enumerate(raw)}
    return {}


def assert_detections_in_image(
    detections: list[BallRacketDetection],
    image_width: int,
    image_height: int,
    tol: float = 1.0,
) -> None:
    """原图坐标契约硬校验（AG）：越界即抛错，绝不放行。"""
    for det in detections:
        if not det.box.is_inside(image_width, image_height, tol=tol):
            raise DetectionError(
                "detection outside original image bounds: "
                f"{det.class_name} {det.box.to_xyxy()} vs {image_width}x{image_height}"
            )


def default_weights_path() -> Path:
    return PATHS.model_out_dir / "best.pt"


def load_detector(weights: str | Path | None = None, device: str | int | None = None):
    """加载 ball+racket 检测器；``weights=None`` 时用本轮训练产物 best.pt。"""
    from ultralytics import YOLO

    path = Path(weights) if weights is not None else default_weights_path()
    if not Path(path).is_file():
        raise FileNotFoundError(
            f"ball+racket weights not found: {path}. 先运行 train_ball_racket.py 完成训练。"
        )
    model = YOLO(str(path))
    if device is not None:
        try:
            model.to(device)
        except Exception:  # noqa: BLE001 - 部分版本不支持直接 to()
            pass
    return model


def detect_ball_racket(
    model,
    image,
    conf: float = INFER_CONF_REPORT,
    iou: float = INFER_IOU,
    imgsz: int = INFER_IMGSZ,
    device: str | int | None = None,
    verify_bounds: bool = True,
) -> tuple[list[BallRacketDetection], dict[int, str]]:
    """在单张图上跑检测器 A，返回原图坐标检测结果。

    使用 ``Results.boxes.xyxy``：Ultralytics 已经把它映射回**原图**，
    因此这里不会输出 640 letterbox 坐标。
    """
    import numpy as np

    names = model_class_names(model)
    array = np.asarray(image)
    if array.ndim != 3:
        raise DetectionError("expected a BGR image array (H, W, 3)")
    image_height, image_width = array.shape[:2]

    predict_kwargs = dict(conf=float(conf), iou=float(iou), imgsz=int(imgsz), verbose=False)
    if device is not None:
        predict_kwargs["device"] = device
    results = model.predict(image, **predict_kwargs)

    detections: list[BallRacketDetection] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            continue
        for xyxy, confidence, class_id in zip(
            boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()
        ):
            class_id = int(class_id)
            detections.append(
                BallRacketDetection(
                    class_id=class_id,
                    class_name=names.get(class_id, str(class_id)),
                    confidence=float(confidence),
                    box=Box(
                        x1=float(xyxy[0]),
                        y1=float(xyxy[1]),
                        x2=float(xyxy[2]),
                        y2=float(xyxy[3]),
                        class_id=class_id,
                        confidence=float(confidence),
                        image_width=int(image_width),
                        image_height=int(image_height),
                    ),
                )
            )
    detections.sort(key=lambda d: -d.confidence)
    if verify_bounds:
        assert_detections_in_image(detections, image_width, image_height)
    return detections, names


def detections_from_label_file(
    label_path: Path,
    image_width: int,
    image_height: int,
    names: dict[int, str] | None = None,
) -> list[BallRacketDetection]:
    """读取 BR 数据集标签为检测结构（用于预测/GT 并排可视化）。"""
    mapping = names or dict(enumerate(CLASS_NAMES))
    label_path = Path(label_path)
    if not label_path.is_file():
        return []
    detections: list[BallRacketDetection] = []
    for line in label_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        class_id = int(float(parts[0]))
        cx, cy, w, h = (float(v) for v in parts[1:])
        box = yolo_norm_to_pixel(class_id, cx, cy, w, h, image_width, image_height)
        detections.append(
            BallRacketDetection(
                class_id=class_id,
                class_name=mapping.get(class_id, str(class_id)),
                confidence=1.0,
                box=box,
            )
        )
    return detections


def class_counts_for_report(detections: list[BallRacketDetection]) -> dict[str, int]:
    counts = {name: 0 for name in CLASS_NAMES}
    for det in detections:
        counts[det.class_name] = counts.get(det.class_name, 0) + 1
    return counts

# ================================================================ FINAL V2 schema (frozen)
# 本节是 C 端收口后的正式输出结构。上面原有的 PerceptionResultV2 保持不动，
# 以免破坏已写好的调用点；新代码请使用 PerceptionResultV2Final。

BALL_STATE_DETECTED = "DETECTED"
BALL_STATE_RECOVERED = "RECOVERED_LOW_CONF"
BALL_STATE_PREDICTED_ONLY = "PREDICTED_ONLY"
BALL_STATE_INVALID = "INVALID"
BALL_STATES = (BALL_STATE_DETECTED, BALL_STATE_RECOVERED,
               BALL_STATE_PREDICTED_ONLY, BALL_STATE_INVALID)

BALL_SOURCE_YOLO = "yolo"
BALL_SOURCE_BALLTRACK = "balltrack"
BALL_SOURCE_NONE = "none"


@dataclass
class PerceptionMetadata:
    """V2 元数据。相机接口目标 1280x720 per eye，但这里不写死尺寸。"""

    source_pair_id: str = ""
    task_id: str = ""
    generation: int = 0
    timestamp: float = 0.0
    frame_id: int = 0
    eye: str = ""              # "left" / "right" / "" (mono)
    original_width: int = 0
    original_height: int = 0

    def to_dict(self) -> dict:
        return {
            "source_pair_id": self.source_pair_id,
            "task_id": self.task_id,
            "generation": int(self.generation),
            "timestamp": float(self.timestamp),
            "frame_id": int(self.frame_id),
            "eye": self.eye,
            "original_width": int(self.original_width),
            "original_height": int(self.original_height),
        }


@dataclass
class BallObservation:
    """ball 观测。state 决定 detected 语义（PREDICTED_ONLY 不是 detection）。"""

    source: str = BALL_SOURCE_NONE
    state: str = BALL_STATE_INVALID
    confidence: float | None = None
    bbox_xyxy: list | None = None
    center_xy: list | None = None
    track_id: int | None = None
    detected: bool = False

    def __post_init__(self) -> None:
        if self.state not in BALL_STATES:
            raise ValueError("invalid ball state: " + str(self.state))
        # 不变式：只有 DETECTED / RECOVERED_LOW_CONF 才算 detector 支持
        if self.state in (BALL_STATE_DETECTED, BALL_STATE_RECOVERED):
            if self.center_xy is None:
                raise ValueError(self.state + " requires a center_xy")
            self.detected = True
        else:
            self.detected = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "state": self.state,
            "confidence": None if self.confidence is None else round(float(self.confidence), 6),
            "bbox_xyxy": [round(float(v), 3) for v in self.bbox_xyxy] if self.bbox_xyxy else None,
            "center_xy": [round(float(v), 3) for v in self.center_xy] if self.center_xy else None,
            "track_id": self.track_id,
            "detected": bool(self.detected),
        }


@dataclass
class RacketObservation:
    confidence: float = 0.0
    bbox_xyxy: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "confidence": round(float(self.confidence), 6),
            "bbox_xyxy": [round(float(v), 3) for v in self.bbox_xyxy],
        }


@dataclass
class WristObservation:
    """手腕**关键点**。禁止把它渲染成 hand bbox。"""

    name: str = ""
    keypoint_index: int = -1
    xy: list | None = None
    confidence: float = 0.0
    valid: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "keypoint_index": int(self.keypoint_index),
            "xy": [round(float(v), 3) for v in self.xy] if self.xy else None,
            "confidence": round(float(self.confidence), 6),
            "valid": bool(self.valid),
            "geometry": "keypoint",
        }


@dataclass
class PersonObservation:
    person_id: int = 0
    bbox_xyxy: list = field(default_factory=list)
    confidence: float = 0.0
    left_wrist: WristObservation | None = None
    right_wrist: WristObservation | None = None

    def to_dict(self) -> dict:
        return {
            "person_id": int(self.person_id),
            "bbox_xyxy": [round(float(v), 3) for v in self.bbox_xyxy],
            "confidence": round(float(self.confidence), 6),
            "left_wrist": self.left_wrist.to_dict() if self.left_wrist else None,
            "right_wrist": self.right_wrist.to_dict() if self.right_wrist else None,
        }


@dataclass
class AssociationObservation:
    """候选关联。status 只能是 HEURISTIC / UNKNOWN，永远不是 GT。"""

    status: str = "UNKNOWN"
    candidate_server_person_id: int | None = None
    candidate_racket_wrist: str | None = None
    candidate_toss_wrist: str | None = None
    confidence: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("HEURISTIC", "UNKNOWN"):
            raise ValueError("association status must be HEURISTIC or UNKNOWN")

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "is_ground_truth": False,
            "candidate_server_person_id": self.candidate_server_person_id,
            "candidate_racket_wrist": self.candidate_racket_wrist,
            "candidate_toss_wrist": self.candidate_toss_wrist,
            "confidence": None if self.confidence is None else round(float(self.confidence), 6),
            "reason": self.reason,
        }


@dataclass
class PerceptionResultV2Final:
    """C 端正式输出（冻结）。所有坐标均为 original eye image coordinates。"""

    metadata: PerceptionMetadata = field(default_factory=PerceptionMetadata)
    ball: BallObservation = field(default_factory=BallObservation)
    rackets: list[RacketObservation] = field(default_factory=list)
    persons: list[PersonObservation] = field(default_factory=list)
    association: AssociationObservation = field(default_factory=AssociationObservation)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "metadata": self.metadata.to_dict(),
            "ball": self.ball.to_dict(),
            "racket": [r.to_dict() for r in self.rackets],
            "persons": [p.to_dict() for p in self.persons],
            "association": self.association.to_dict(),
        }

    def to_json(self) -> str:
        import json as _json

        return _json.dumps(self.to_dict(), ensure_ascii=False)


def to_legacy_boxes(result: PerceptionResultV2Final) -> list[dict]:
    """Legacy adapter：输出旧 DetectionResult.boxes 兼容的形状。

    只输出 ball 与 racket。**绝不输出 hand**——旧 hand 类别已永久取消，
    且不会围绕 wrist 伪造 hand rectangle。
    """
    boxes: list[dict] = []
    if result.ball.detected and result.ball.bbox_xyxy:
        boxes.append({
            "class_name": "ball",
            "class_id": CLASS_BALL,
            "confidence": float(result.ball.confidence or 0.0),
            "bbox_xyxy": [float(v) for v in result.ball.bbox_xyxy],
        })
    elif result.ball.detected and result.ball.center_xy:
        # BallTrack 只给中心点：给一个零面积占位框，调用方应按 center 处理
        cx, cy = (float(result.ball.center_xy[0]), float(result.ball.center_xy[1]))
        boxes.append({
            "class_name": "ball",
            "class_id": CLASS_BALL,
            "confidence": float(result.ball.confidence or 0.0),
            "bbox_xyxy": [cx, cy, cx, cy],
            "geometry": "center_only",
        })
    for racket in result.rackets:
        boxes.append({
            "class_name": "racket",
            "class_id": CLASS_RACKET,
            "confidence": float(racket.confidence),
            "bbox_xyxy": [float(v) for v in racket.bbox_xyxy],
        })
    return boxes


__all__ = [
    "BallObservation",
    "AssociationObservation",
    "BallRacketDetection",
    "DetectionError",
    "PerceptionMetadata",
    "PerceptionResultV2",
    "PerceptionResultV2Final",
    "PersonObservation",
    "PosePersonLite",
    "RacketObservation",
    "WristObservation",
    "assert_detections_in_image",
    "class_counts_for_report",
    "default_weights_path",
    "detect_ball_racket",
    "detections_from_label_file",
    "load_detector",
    "model_class_names",
    "to_legacy_boxes",
    "BALL_STATES",
    "BALL_STATE_DETECTED",
    "BALL_STATE_INVALID",
    "BALL_STATE_PREDICTED_ONLY",
    "BALL_STATE_RECOVERED",
    "BALL_SOURCE_BALLTRACK",
    "BALL_SOURCE_NONE",
    "BALL_SOURCE_YOLO",
]