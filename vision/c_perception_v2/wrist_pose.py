"""检测器 B：YOLOv8n-Pose，只取 COCO 17 关键点里的两只手腕。

关键约定（V/W）
---------------
* Python 0-based：``index 9 = left_wrist``，``index 10 = right_wrist``；
* pose 输出的是 **关键点**，不是 hand bbox。本模块**绝不**围绕手腕伪造方框；
* 手腕置信度低于阈值时输出 ``valid=False`` 且 ``xy=None``，不编造坐标；
* 不做任何训练，直接用公开 pretrained ``yolov8n-pose.pt``；
* 默认保留画面中**所有** person（发球员/接球员/背景人员都不提前丢弃）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import PATHS, WRIST_CONF_MIN

# COCO 17 关键点名称与索引（0-based）
COCO_KEYPOINT_NAMES: tuple[str, ...] = (
    "nose",           # 0
    "left_eye",       # 1
    "right_eye",      # 2
    "left_ear",       # 3
    "right_ear",      # 4
    "left_shoulder",  # 5
    "right_shoulder", # 6
    "left_elbow",     # 7
    "right_elbow",    # 8
    "left_wrist",     # 9
    "right_wrist",    # 10
    "left_hip",       # 11
    "right_hip",      # 12
    "left_knee",      # 13
    "right_knee",     # 14
    "left_ankle",     # 15
    "right_ankle",    # 16
)
LEFT_WRIST_INDEX = 9
RIGHT_WRIST_INDEX = 10

# 画骨架用的连接（只用上半身，避免视觉噪声盖住球）
SKELETON_EDGES: tuple[tuple[int, int], ...] = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
)


@dataclass(frozen=True)
class Keypoint:
    """单个关键点；``valid=False`` 时 ``xy`` 必须为 ``None``。"""

    index: int
    name: str
    xy: tuple[float, float] | None
    confidence: float
    valid: bool

    def to_dict(self) -> dict:
        return {
            "index": int(self.index),
            "name": self.name,
            "xy": [round(float(self.xy[0]), 3), round(float(self.xy[1]), 3)]
            if self.xy is not None
            else None,
            "confidence": round(float(self.confidence), 6),
            "valid": bool(self.valid),
        }


@dataclass
class PersonPose:
    """一个人的姿态结果（原图坐标）。"""

    person_id: int
    bbox_xyxy: tuple[float, float, float, float]
    person_confidence: float
    keypoints: list[Keypoint] = field(default_factory=list)

    def keypoint(self, index: int) -> Keypoint | None:
        for kp in self.keypoints:
            if kp.index == index:
                return kp
        return None

    @property
    def left_wrist(self) -> Keypoint | None:
        return self.keypoint(LEFT_WRIST_INDEX)

    @property
    def right_wrist(self) -> Keypoint | None:
        return self.keypoint(RIGHT_WRIST_INDEX)

    @property
    def bbox_center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_xyxy
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def to_dict(self) -> dict:
        return {
            "person_id": int(self.person_id),
            "bbox_xyxy": [round(float(v), 3) for v in self.bbox_xyxy],
            "person_confidence": round(float(self.person_confidence), 6),
            "left_wrist": _wrist_dict(self.left_wrist, "left_wrist"),
            "right_wrist": _wrist_dict(self.right_wrist, "right_wrist"),
            "keypoints": [kp.to_dict() for kp in self.keypoints],
        }


def _wrist_dict(keypoint: Keypoint | None, name: str) -> dict:
    if keypoint is None:
        return {"name": name, "xy": None, "confidence": 0.0, "valid": False}
    return {
        "name": name,
        "xy": [round(float(keypoint.xy[0]), 3), round(float(keypoint.xy[1]), 3)]
        if keypoint.xy is not None
        else None,
        "confidence": round(float(keypoint.confidence), 6),
        "valid": bool(keypoint.valid),
    }


@dataclass
class PoseFrame:
    """一帧的 pose 结果（可含多人）。"""

    persons: list[PersonPose] = field(default_factory=list)

    @property
    def person_count(self) -> int:
        return len(self.persons)

    def wrist_records(self) -> list[dict]:
        """扁平化手腕列表，供 :class:`PerceptionResultV2.wrists` 与融合使用。"""
        records: list[dict] = []
        for person in self.persons:
            for keypoint, name in (
                (person.left_wrist, "left_wrist"),
                (person.right_wrist, "right_wrist"),
            ):
                records.append(
                    {
                        "person_id": person.person_id,
                        "wrist": name,
                        "keypoint_index": keypoint.index if keypoint else None,
                        "xy": list(keypoint.xy) if keypoint and keypoint.xy else None,
                        "confidence": float(keypoint.confidence) if keypoint else 0.0,
                        "valid": bool(keypoint.valid) if keypoint else False,
                    }
                )
        return records

    def count_valid_wrists(self) -> tuple[int, int, int]:
        """返回 ``(both_valid, one_valid_only, none_valid)`` 的 person 计数。"""
        both = one = none = 0
        for person in self.persons:
            left = bool(person.left_wrist and person.left_wrist.valid)
            right = bool(person.right_wrist and person.right_wrist.valid)
            if left and right:
                both += 1
            elif left or right:
                one += 1
            else:
                none += 1
        return both, one, none

    def to_dict(self) -> dict:
        both, one, none = self.count_valid_wrists()
        return {
            "person_count": self.person_count,
            "both_wrists_valid": both,
            "one_wrist_valid": one,
            "no_wrist_valid": none,
            "persons": [p.to_dict() for p in self.persons],
        }


def load_pose_model(weights: str | Path | None = None, device: str | int | None = None):
    """加载公开 pretrained pose 模型（不训练）。"""
    from ultralytics import YOLO

    path = Path(weights) if weights is not None else PATHS.pose_weights_path
    model = YOLO(str(path))
    if device is not None:
        try:
            model.to(device)
        except Exception:  # noqa: BLE001
            pass
    return model


def build_person_pose(
    person_id: int,
    bbox: tuple[float, float, float, float],
    person_confidence: float,
    keypoints_xy: list[tuple[float, float]],
    keypoints_conf: list[float],
    wrist_conf_min: float = WRIST_CONF_MIN,
) -> PersonPose:
    """把原始 keypoint 数组转成 :class:`PersonPose`。

    置信度不足的手腕：``valid=False`` 且 ``xy=None``（不造坐标）。
    """
    if len(keypoints_xy) != len(COCO_KEYPOINT_NAMES) or len(keypoints_conf) != len(
        COCO_KEYPOINT_NAMES
    ):
        raise ValueError(
            "unexpected keypoint count: "
            f"{len(keypoints_xy)}/{len(keypoints_conf)} (expected 17)"
        )
    keypoints: list[Keypoint] = []
    for index, name in enumerate(COCO_KEYPOINT_NAMES):
        confidence = float(keypoints_conf[index])
        x, y = keypoints_xy[index]
        valid = confidence >= float(wrist_conf_min) and _finite(x) and _finite(y)
        keypoints.append(
            Keypoint(
                index=index,
                name=name,
                xy=(float(x), float(y)) if valid else None,
                confidence=confidence,
                valid=valid,
            )
        )
    return PersonPose(
        person_id=int(person_id),
        bbox_xyxy=tuple(float(v) for v in bbox),
        person_confidence=float(person_confidence),
        keypoints=keypoints,
    )


def _finite(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in (float("inf"), float("-inf"))


def infer_pose(
    model,
    image,
    conf: float = 0.25,
    imgsz: int = 640,
    device: str | int | None = None,
    wrist_conf_min: float = WRIST_CONF_MIN,
    verify_bounds: bool = True,
) -> PoseFrame:
    """在单张图上跑 pose，返回原图坐标的 :class:`PoseFrame`。

    ``Results.keypoints.xy`` 已由 Ultralytics 映射回原图坐标；这里仍然断言
    person bbox 落在原图内（AG 的坐标契约）。
    """
    import numpy as np

    array = np.asarray(image)
    if array.ndim != 3:
        raise ValueError("expected a BGR image array (H, W, 3)")
    image_height, image_width = array.shape[:2]

    predict_kwargs = dict(conf=float(conf), imgsz=int(imgsz), verbose=False)
    if device is not None:
        predict_kwargs["device"] = device
    results = model.predict(array, **predict_kwargs)

    persons: list[PersonPose] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        keypoints = getattr(result, "keypoints", None)
        if boxes is None or keypoints is None or len(boxes) == 0:
            continue
        bboxes = boxes.xyxy.tolist()
        confidences = boxes.conf.tolist()
        xy_list = keypoints.xy.tolist()
        kp_conf = (
            keypoints.conf.tolist()
            if getattr(keypoints, "conf", None) is not None
            else [[1.0] * len(COCO_KEYPOINT_NAMES) for _ in xy_list]
        )
        for index, (bbox, confidence, xy, kp_confidence) in enumerate(
            zip(bboxes, confidences, xy_list, kp_conf)
        ):
            if verify_bounds:
                x1, y1, x2, y2 = (float(v) for v in bbox)
                if (
                    x1 < -1.0
                    or y1 < -1.0
                    or x2 > image_width + 1.0
                    or y2 > image_height + 1.0
                ):
                    raise ValueError(
                        f"person bbox outside original image: {bbox} vs "
                        f"{image_width}x{image_height}"
                    )
            persons.append(
                build_person_pose(
                    person_id=index,
                    bbox=tuple(float(v) for v in bbox),
                    person_confidence=float(confidence),
                    keypoints_xy=[(float(p[0]), float(p[1])) for p in xy],
                    keypoints_conf=[float(v) for v in kp_confidence],
                    wrist_conf_min=wrist_conf_min,
                )
            )
    persons.sort(key=lambda p: -p.person_confidence)
    for order, person in enumerate(persons):
        person.person_id = order
    return PoseFrame(persons=persons)


def draw_pose_person(image, person: PersonPose, color=(180, 180, 180), draw_skeleton: bool = True):
    """淡色 person bbox + 骨架；手腕由 :mod:`fusion_demo` 单独强调。"""
    from .yolo_io import Box, draw_box

    x1, y1, x2, y2 = person.bbox_xyxy
    box = Box(x1, y1, x2, y2, class_id=-1, confidence=person.person_confidence)
    draw_box(
        image,
        box,
        label=f"person {person.person_id} {person.person_confidence:.2f}",
        color=color,
        thickness=1,
        dashed=True,
    )
    if draw_skeleton:
        import cv2

        for start, end in SKELETON_EDGES:
            a = person.keypoint(start)
            b = person.keypoint(end)
            if a and b and a.valid and b.valid:
                cv2.line(
                    image,
                    (int(round(a.xy[0])), int(round(a.xy[1]))),
                    (int(round(b.xy[0])), int(round(b.xy[1]))),
                    color,
                    1,
                    cv2.LINE_AA,
                )
    return image


__all__ = [
    "COCO_KEYPOINT_NAMES",
    "LEFT_WRIST_INDEX",
    "RIGHT_WRIST_INDEX",
    "SKELETON_EDGES",
    "Keypoint",
    "PersonPose",
    "PoseFrame",
    "build_person_pose",
    "draw_pose_person",
    "infer_pose",
    "load_pose_model",
]
