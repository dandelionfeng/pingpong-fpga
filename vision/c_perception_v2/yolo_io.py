"""YOLO 框几何：归一化 ↔ 像素 ↔ 原图坐标，以及统一的绘图层。

坐标契约（AG）
--------------
* 磁盘上的 YOLO 标签是 ``class cx cy w h`` 归一化浮点；
* 本模块内部一律用 **原图像素** 的 ``xyxy``，并用 :class:`Box` 记录所属图像尺寸；
* :meth:`Box.is_inside` 是“原图坐标还原”的自检钩子：任何越界框都会被审计脚本抓出来；
* Ultralytics 的 ``Results.boxes.xyxy`` 已经映射回原图，因此推理侧直接取用，
  禁止把 640 letterbox 坐标当作最终坐标输出。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

# ---------------------------------------------------------------- 调色板
COLOR_BALL = (0, 165, 255)      # BGR 橙
COLOR_RACKET = (0, 255, 0)      # BGR 绿
COLOR_PERSON = (180, 180, 180)  # BGR 浅灰（淡一点）
COLOR_WRIST_L = (255, 128, 0)   # BGR 蓝
COLOR_WRIST_R = (255, 0, 255)   # BGR 品红
COLOR_RACKET_WRIST = (0, 0, 255)  # BGR 红：candidate racket wrist
COLOR_TOSS_WRIST = (255, 255, 0)  # BGR 青：candidate toss wrist
COLOR_GT = (60, 220, 60)
COLOR_PRED = (30, 30, 255)
COLOR_TEXT = (255, 255, 255)


@dataclass(frozen=True)
class Box:
    """原图像素坐标下的 xyxy 框。"""

    x1: float
    y1: float
    x2: float
    y2: float
    class_id: int = -1
    confidence: float = 1.0
    image_width: int = 0
    image_height: int = 0

    # --- 基本属性 ------------------------------------------------------
    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def area_ratio(self, image_width: int | None = None, image_height: int | None = None) -> float:
        width = image_width or self.image_width
        height = image_height or self.image_height
        if not width or not height:
            return float("nan")
        return self.area / float(width * height)

    def is_inside(
        self,
        image_width: int | None = None,
        image_height: int | None = None,
        tol: float = 1e-6,
    ) -> bool:
        """是否为合法原始图像坐标（有限、非退化、完全落在画面内）。"""
        width = image_width or self.image_width
        height = image_height or self.image_height
        values = (self.x1, self.y1, self.x2, self.y2)
        if any(v is None or not math.isfinite(float(v)) for v in values):
            return False
        if self.width <= 0 or self.height <= 0:
            return False
        if not width or not height:
            return True
        return (
            self.x1 >= -tol
            and self.y1 >= -tol
            and self.x2 <= float(width) + tol
            and self.y2 <= float(height) + tol
        )

    def to_xyxy(self) -> list[float]:
        return [float(self.x1), float(self.y1), float(self.x2), float(self.y2)]

    def to_dict(self) -> dict:
        return {
            "class_id": int(self.class_id),
            "confidence": round(float(self.confidence), 6),
            "bbox_xyxy": [round(v, 3) for v in self.to_xyxy()],
        }

    def with_size(self, image_width: int, image_height: int) -> "Box":
        return replace(self, image_width=int(image_width), image_height=int(image_height))


# ---------------------------------------------------------------- 转换
def yolo_norm_to_pixel(
    class_id: int,
    cx: float,
    cy: float,
    w: float,
    h: float,
    image_width: int,
    image_height: int,
    confidence: float = 1.0,
) -> Box:
    """归一化 ``cx cy w h`` → 原图像素 xyxy。"""
    width = float(w) * image_width
    height = float(h) * image_height
    x_center = float(cx) * image_width
    y_center = float(cy) * image_height
    return Box(
        x1=x_center - width / 2.0,
        y1=y_center - height / 2.0,
        x2=x_center + width / 2.0,
        y2=y_center + height / 2.0,
        class_id=int(class_id),
        confidence=float(confidence),
        image_width=int(image_width),
        image_height=int(image_height),
    )


def pixel_to_yolo_norm(box: Box, image_width: int, image_height: int) -> tuple[float, float, float, float]:
    """原图像素 xyxy → 归一化 ``cx cy w h``（用于标签回环测试）。"""
    cx = (box.x1 + box.x2) / 2.0 / float(image_width)
    cy = (box.y1 + box.y2) / 2.0 / float(image_height)
    w = box.width / float(image_width)
    h = box.height / float(image_height)
    return (cx, cy, w, h)


def yolo_line_is_valid(parts: list[str], image_width: int, image_height: int) -> tuple[bool, str]:
    """校验一行 YOLO 标签：5 列、类别整数、归一化在 [0,1]、面积非零。

    返回 ``(ok, reason)``；``reason`` 用于审计报告，空字符串表示通过。
    """
    if len(parts) != 5:
        return False, f"expected 5 columns, got {len(parts)}"
    try:
        class_id = int(float(parts[0]))
        cx, cy, w, h = (float(v) for v in parts[1:])
    except (TypeError, ValueError):
        return False, "non-numeric field"
    values = (cx, cy, w, h)
    if any(not math.isfinite(v) for v in values):
        return False, "NaN/Inf value"
    if class_id < 0:
        return False, f"negative class id {class_id}"
    if w <= 0 or h <= 0:
        return False, "zero-area box"
    if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
        return False, f"center out of [0,1]: {cx},{cy}"
    if not (0.0 < w <= 1.0 and 0.0 < h <= 1.0):
        return False, f"size out of (0,1]: {w},{h}"
    # 允许浮点误差，但明显越界的框必须拒绝
    x1 = (cx - w / 2.0) * image_width
    y1 = (cy - h / 2.0) * image_height
    x2 = (cx + w / 2.0) * image_width
    y2 = (cy + h / 2.0) * image_height
    tol = 1.0
    if x1 < -tol or y1 < -tol or x2 > image_width + tol or y2 > image_height + tol:
        return False, "bbox out of image bounds"
    return True, ""


# ---------------------------------------------------------------- 距离
def distance_point_to_box(point: tuple[float, float], box: Box) -> float:
    """点到框的最短欧氏距离；点在框内返回 0。"""
    px, py = float(point[0]), float(point[1])
    dx = max(box.x1 - px, 0.0, px - box.x2)
    dy = max(box.y1 - py, 0.0, py - box.y2)
    return math.hypot(dx, dy)


def box_contains_point(box: Box, point: tuple[float, float], margin: float = 0.0) -> bool:
    px, py = float(point[0]), float(point[1])
    return (
        box.x1 - margin <= px <= box.x2 + margin
        and box.y1 - margin <= py <= box.y2 + margin
    )


def box_iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def nearest_box(boxes: list[Box], point: tuple[float, float]) -> tuple[Box | None, float]:
    """返回距离该点最近的框及其距离。"""
    best: Box | None = None
    best_distance = float("inf")
    for box in boxes:
        distance = distance_point_to_box(point, box)
        if distance < best_distance:
            best, best_distance = box, distance
    return best, best_distance


# ---------------------------------------------------------------- 绘制
def draw_box(
    image,
    box: Box,
    label: str = "",
    color: tuple[int, int, int] = COLOR_PRED,
    thickness: int = 2,
    dashed: bool = False,
):
    """在图像上画框；``dashed=True`` 用虚线（用于预测框区分 GT）。"""
    import cv2  # 局部导入，便于无 cv2 环境下做纯几何测试

    p1 = (int(round(box.x1)), int(round(box.y1)))
    p2 = (int(round(box.x2)), int(round(box.y2)))
    if dashed:
        _draw_dashed_rect(image, p1, p2, color, thickness)
    else:
        cv2.rectangle(image, p1, p2, color, thickness)
    if label:
        draw_label(image, label, (p1[0], max(0, p1[1] - 16)), color, text_color=COLOR_TEXT)
    return image


def _draw_dashed_rect(image, p1, p2, color, thickness, dash: int = 8):
    import cv2

    x1, y1 = p1
    x2, y2 = p2
    for x in range(x1, x2, dash * 2):
        cv2.line(image, (x, y1), (min(x + dash, x2), y1), color, thickness)
        cv2.line(image, (x, y2), (min(x + dash, x2), y2), color, thickness)
    for y in range(y1, y2, dash * 2):
        cv2.line(image, (x1, y), (x1, min(y + dash, y2)), color, thickness)
        cv2.line(image, (x2, y), (x2, min(y + dash, y2)), color, thickness)


def draw_label(
    image,
    text: str,
    origin: tuple[int, int],
    box_color: tuple[int, int, int],
    text_color: tuple[int, int, int] = COLOR_TEXT,
    scale: float = 0.45,
):
    """带底色的小标签，保证在任意背景上可读。"""
    import cv2

    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, 1)
    x, y = int(origin[0]), int(origin[1])
    top = max(0, y)
    cv2.rectangle(
        image,
        (x, top),
        (x + text_width + 6, top + text_height + baseline + 4),
        box_color,
        -1,
    )
    cv2.putText(
        image,
        text,
        (x + 3, top + text_height + 2),
        font,
        scale,
        text_color,
        1,
        cv2.LINE_AA,
    )
    return image


def draw_wrist(
    image,
    point: tuple[float, float],
    color: tuple[int, int, int],
    label: str = "",
    radius: int = 6,
    cross: bool = True,
):
    """画手腕关键点：实心圆 + 十字准心（强调“这是一个点，不是手部框”）。"""
    import cv2

    px, py = int(round(point[0])), int(round(point[1]))
    cv2.circle(image, (px, py), radius, color, -1, cv2.LINE_AA)
    cv2.circle(image, (px, py), radius + 2, (255, 255, 255), 1, cv2.LINE_AA)
    if cross:
        cv2.line(image, (px - radius - 6, py), (px + radius + 6, py), color, 1, cv2.LINE_AA)
        cv2.line(image, (px, py - radius - 6), (px, py + radius + 6), color, 1, cv2.LINE_AA)
    if label:
        draw_label(image, label, (px + radius + 4, py - 20), color)
    return image


def draw_legend(image, entries: list[tuple[str, tuple[int, int, int]]], origin: tuple[int, int] = (8, 8)):
    """左上角图例；``entries`` 为 ``[(文字, BGR)]``。"""
    import cv2

    x, y = origin
    line_height = 18
    width = 0
    font = cv2.FONT_HERSHEY_SIMPLEX
    for text, _ in entries:
        (text_width, _), _ = cv2.getTextSize(text, font, 0.45, 1)
        width = max(width, text_width)
    height = line_height * len(entries) + 8
    overlay = image.copy()
    cv2.rectangle(overlay, (x, y), (x + width + 34, y + height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, image, 0.45, 0, image)
    for index, (text, color) in enumerate(entries):
        top = y + 6 + index * line_height
        cv2.rectangle(image, (x + 6, top + 3), (x + 20, top + 13), color, -1)
        cv2.putText(
            image,
            text,
            (x + 26, top + 13),
            font,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return image


# ---------------------------------------------------------------- 文件工具
def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_image_size(path: Path) -> tuple[int, int]:
    """快速读取图像尺寸（不解码整图）。"""
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_8)
    if image is None:
        raise ValueError(f"cannot read image: {path}")
    height, width = image.shape[:2]
    return width * 8, height * 8


def read_image_size_exact(path: Path) -> tuple[int, int]:
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot read image: {path}")
    height, width = image.shape[:2]
    return width, height
