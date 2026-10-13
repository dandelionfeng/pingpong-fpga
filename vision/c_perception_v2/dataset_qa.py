"""BR 数据集读取、QA 可视化与 contact sheet 拼接。

QA 图只画**转换后的 GT**（ball bbox / racket bbox），用于人工快速判断标签是否明显异常。
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from . import CLASS_NAMES
from .config import PATHS
from .yolo_io import (
    COLOR_BALL,
    COLOR_RACKET,
    Box,
    draw_box,
    draw_label,
    draw_legend,
    yolo_line_is_valid,
    yolo_norm_to_pixel,
)

THUMB_WIDTH = 384
GRID_COLUMNS = 6


@dataclass(frozen=True)
class Sample:
    """BR 数据集中的一个样本（原图 + 标签）。"""

    split: str
    image_path: Path
    label_path: Path
    image_width: int
    image_height: int


def dataset_root_from_yaml(data_yaml: Path) -> Path:
    import yaml

    payload = yaml.safe_load(Path(data_yaml).read_text(encoding="utf-8"))
    raw_path = payload.get("path")
    if not raw_path:
        return Path(data_yaml).parent
    root = Path(raw_path)
    return root if root.is_absolute() else (Path(data_yaml).parent / root).resolve()


def load_split_samples(br_dir: Path, split: str) -> list[Sample]:
    """加载某个 split 的 (image, label) 对并读取图像尺寸。"""
    from PIL import Image

    br_dir = Path(br_dir)
    image_dir = br_dir / "images" / split
    label_dir = br_dir / "labels" / split
    if not image_dir.is_dir():
        return []
    samples: list[Sample] = []
    for image_path in sorted(image_dir.iterdir()):
        if not image_path.is_file():
            continue
        label_path = label_dir / f"{image_path.stem}.txt"
        try:
            with Image.open(image_path) as handle:
                width, height = handle.size
        except Exception:
            continue
        samples.append(Sample(split, image_path, label_path, width, height))
    return samples


def read_label_boxes(
    sample: Sample, names: dict[int, str] | None = None
) -> tuple[list[Box], list[str]]:
    """读标签为原图坐标框；返回 ``(boxes, errors)``。"""
    _ = names
    boxes: list[Box] = []
    errors: list[str] = []
    if not sample.label_path.is_file():
        return boxes, errors
    for line_number, line in enumerate(
        sample.label_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        ok, reason = yolo_line_is_valid(parts, sample.image_width, sample.image_height)
        if not ok:
            errors.append(f"{sample.label_path.name}:{line_number} {reason}")
            continue
        class_id = int(float(parts[0]))
        cx, cy, w, h = (float(v) for v in parts[1:])
        boxes.append(
            yolo_norm_to_pixel(class_id, cx, cy, w, h, sample.image_width, sample.image_height)
        )
    return boxes, errors


def box_color(class_id: int) -> tuple[int, int, int]:
    return COLOR_BALL if class_id == 0 else COLOR_RACKET


def draw_gt_boxes(image, boxes: list[Box], with_labels: bool = True):
    for box in boxes:
        name = (
            CLASS_NAMES[box.class_id]
            if 0 <= box.class_id < len(CLASS_NAMES)
            else str(box.class_id)
        )
        label = f"{name} {box.width:.0f}x{box.height:.0f}" if with_labels else ""
        draw_box(image, box, label=label, color=box_color(box.class_id), thickness=2)
    return image


def write_image_robust(path, image, jpeg_quality: int = 88) -> bool:
    """稳健写图（JPEG/PNG）。

    本机环境（Windows + 含中文的长路径）下 ``cv2.imwrite`` 会静默返回 False，
    因此改为 ``cv2.imencode`` 编码后由 Python 写盘，必要时再退回 PIL。
    返回 True 表示磁盘上确实出现了非空文件。
    """
    import cv2
    import numpy as np

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.ascontiguousarray(image)
    params = []
    if path.suffix.lower() in (".jpg", ".jpeg"):
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]
    try:
        ok, buffer = cv2.imencode(path.suffix, image, params)
    except cv2.error:
        ok, buffer = False, None
    if ok and buffer is not None:
        buffer.tofile(str(path))
        if path.is_file() and path.stat().st_size > 0:
            return True
    try:
        from PIL import Image

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        Image.fromarray(rgb).save(str(path), quality=int(jpeg_quality))
        return path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def read_image_robust(path: Path, attempts: int = 3, delay: float = 0.12):
    """稳健读图（BGR uint8）。

    本机环境（Windows + 含中文的长路径）下 ``cv2.imread`` 会静默返回 None，
    因此这里按顺序尝试：
      1. ``cv2.imread``；
      2. Python 读字节 + ``cv2.imdecode``（绕开 OpenCV 的窄字符 fopen）；
      3. PIL 打开再转 BGR。
    三条都失败才返回 None，调用方据此跳过该图而不是整体崩溃。
    """
    import time

    import cv2
    import numpy as np

    path = Path(path)
    for attempt in range(max(1, attempts)):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is not None:
            return image
        try:
            raw = path.read_bytes()
            if raw:
                buffer = np.frombuffer(raw, dtype=np.uint8)
                image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                if image is not None:
                    return image
        except OSError:
            pass
        try:
            from PIL import Image

            with Image.open(path) as handle:
                rgb = handle.convert("RGB")
                array = np.asarray(rgb)
                if array.size:
                    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
        except Exception:
            pass
        if attempt + 1 < attempts:
            time.sleep(delay)
    return None


def make_thumbnail(image, width: int = THUMB_WIDTH):
    import cv2

    height, current_width = image.shape[:2]
    scale = width / float(current_width)
    return cv2.resize(
        image, (width, max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA
    )


def contact_sheet(
    panels: list,
    columns: int = GRID_COLUMNS,
    panel_width: int = THUMB_WIDTH,
    background: tuple[int, int, int] = (24, 24, 24),
):
    """把多张同宽缩略图拼成网格（自动补底色格）。"""
    import cv2
    import numpy as np

    if not panels:
        raise ValueError("no panels to compose")
    thumbs = [make_thumbnail(panel, panel_width) for panel in panels]
    cell_height = max(thumb.shape[0] for thumb in thumbs)
    rows = int(math.ceil(len(thumbs) / float(columns)))
    sheet = np.full((cell_height * rows, panel_width * columns, 3), background, dtype=np.uint8)
    for index, thumb in enumerate(thumbs):
        row, column = divmod(index, columns)
        top, left = row * cell_height, column * panel_width
        sheet[top : top + thumb.shape[0], left : left + thumb.shape[1]] = thumb
        cv2.rectangle(
            sheet,
            (left, top),
            (left + panel_width - 1, top + cell_height - 1),
            (70, 70, 70),
            1,
        )
    return sheet


def label_samples_by_count(samples: list[Sample]) -> dict[str, list[Sample]]:
    """按 ball/racket 实例数把样本分组，便于挑出 tiny ball 等极端案例。"""
    groups: dict[str, list[Sample]] = {"ball": [], "racket": [], "both": [], "none": []}
    for sample in samples:
        boxes, _ = read_label_boxes(sample)
        has_ball = any(box.class_id == 0 for box in boxes)
        has_racket = any(box.class_id == 1 for box in boxes)
        if has_ball and has_racket:
            groups["both"].append(sample)
        elif has_ball:
            groups["ball"].append(sample)
        elif has_racket:
            groups["racket"].append(sample)
        else:
            groups["none"].append(sample)
    return groups


def write_qa_split_report(samples: list[Sample], path: Path, split: str) -> Path:
    """每个 split 的逐图统计（ball/racket 数量与像素尺寸），CSV 便于外部核对。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "split", "image", "width", "height", "ball_count", "racket_count",
                "ball_w_px", "ball_h_px", "racket_w_px", "racket_h_px",
            ]
        )
        for sample in samples:
            boxes, _ = read_label_boxes(sample)
            balls = [b for b in boxes if b.class_id == 0]
            rackets = [b for b in boxes if b.class_id == 1]
            writer.writerow(
                [
                    split,
                    sample.image_path.name,
                    sample.image_width,
                    sample.image_height,
                    len(balls),
                    len(rackets),
                    ";".join(f"{b.width:.1f}" for b in balls),
                    ";".join(f"{b.height:.1f}" for b in balls),
                    ";".join(f"{b.width:.1f}" for b in rackets),
                    ";".join(f"{b.height:.1f}" for b in rackets),
                ]
            )
    return path


def render_gt_panel(sample: Sample):
    """渲染单张 GT 面板（原图 + GT 框 + 文件名 + 图例）。"""
    import cv2

    image = read_image_robust(sample.image_path)
    if image is None:
        raise ValueError(f"cannot read image after retries: {sample.image_path}")
    boxes, _ = read_label_boxes(sample)
    draw_gt_boxes(image, boxes)
    draw_legend(
        image,
        [
            (f"GT ball ({sum(1 for b in boxes if b.class_id == 0)})", COLOR_BALL),
            (f"GT racket ({sum(1 for b in boxes if b.class_id == 1)})", COLOR_RACKET),
        ],
    )
    draw_label(image, sample.image_path.name, (8, image.shape[0] - 26), (40, 40, 40), scale=0.5)
    return image


def build_dataset_qa(br_dir: Path | None = None, out_dir: Path | None = None) -> dict:
    """生成 train/val/test 的随机 GT 抽样 contact sheet 与逐图 CSV。"""
    import cv2
    import numpy as np

    root = Path(br_dir) if br_dir is not None else PATHS.br_dir
    out = Path(out_dir) if out_dir is not None else PATHS.qa_dir
    out.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict] = {}
    for split, take, seed in (("train", 50, 11), ("val", 30, 22), ("test", 30, 33)):
        samples = load_split_samples(root, split)
        if not samples:
            summary[split] = {"samples": 0, "note": "split missing"}
            continue
        write_qa_split_report(samples, out / f"{split}_per_image.csv", split)
        rng = np.random.default_rng(seed)
        count = min(take, len(samples))
        picked = [int(i) for i in rng.choice(len(samples), size=count, replace=False)]
        selected = [samples[i] for i in sorted(picked)]
        panels = []
        unreadable: list[str] = []
        for sample in selected:
            try:
                panels.append(render_gt_panel(sample))
            except ValueError as exc:
                unreadable.append(sample.image_path.name)
                print("[qa] skip unreadable: " + str(exc))
        target = out / f"{split}_random_{take}.jpg"
        if panels:
            sheet = contact_sheet(panels, columns=GRID_COLUMNS)
            if not write_image_robust(target, sheet):
                print("[qa] WARNING: failed to write " + str(target))
        groups = label_samples_by_count(samples)
        summary[split] = {
            "samples": len(samples),
            "panels": len(panels),
            "unreadable_panels": unreadable,
            "sheet": str(target),
            "images_with_ball": len(groups["ball"]) + len(groups["both"]),
            "images_with_racket": len(groups["racket"]) + len(groups["both"]),
            "images_with_both": len(groups["both"]),
            "zero_target_images": len(groups["none"]),
        }
    return summary


def collect_ball_sizes(br_dir: Path | None = None, out_csv: Path | None = None) -> dict:
    """统计 public dataset 中 ball bbox 的像素宽高与面积占比（AK）。"""
    root = Path(br_dir) if br_dir is not None else PATHS.br_dir
    target = (
        Path(out_csv) if out_csv is not None else PATHS.reports_dir / "ball_size_distribution.csv"
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for split in ("train", "val", "test"):
        for sample in load_split_samples(root, split):
            boxes, _ = read_label_boxes(sample)
            for index, box in enumerate(boxes):
                if box.class_id != 0:
                    continue
                rows.append(
                    {
                        "split": split,
                        "image": sample.image_path.name,
                        "instance": index,
                        "image_width": sample.image_width,
                        "image_height": sample.image_height,
                        "bbox_w_px": round(box.width, 3),
                        "bbox_h_px": round(box.height, 3),
                        "bbox_area_px": round(box.area, 3),
                        "bbox_area_ratio": round(
                            box.area_ratio(sample.image_width, sample.image_height), 8
                        ),
                        "bbox_w_norm": round(box.width / sample.image_width, 6),
                        "bbox_h_norm": round(box.height / sample.image_height, 6),
                    }
                )

    fieldnames = [
        "split", "image", "instance", "image_width", "image_height",
        "bbox_w_px", "bbox_h_px", "bbox_area_px", "bbox_area_ratio",
        "bbox_w_norm", "bbox_h_norm",
    ]
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    widths = sorted(row["bbox_w_px"] for row in rows)
    heights = sorted(row["bbox_h_px"] for row in rows)
    ratios = sorted(row["bbox_area_ratio"] for row in rows)

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
        return float(values[index])

    return {
        "count": len(rows),
        "csv": str(target),
        "width_px": {
            "min": widths[0] if widths else None,
            "p10": percentile(widths, 0.10),
            "median": percentile(widths, 0.50),
            "p90": percentile(widths, 0.90),
            "max": widths[-1] if widths else None,
        },
        "height_px": {
            "min": heights[0] if heights else None,
            "p10": percentile(heights, 0.10),
            "median": percentile(heights, 0.50),
            "p90": percentile(heights, 0.90),
            "max": heights[-1] if heights else None,
        },
        "area_ratio": {
            "min": ratios[0] if ratios else None,
            "median": percentile(ratios, 0.50),
            "max": ratios[-1] if ratios else None,
        },
    }


__all__ = [
    "Sample",
    "THUMB_WIDTH",
    "build_dataset_qa",
    "collect_ball_sizes",
    "contact_sheet",
    "dataset_root_from_yaml",
    "draw_gt_boxes",
    "label_samples_by_count",
    "load_split_samples",
    "make_thumbnail",
    "read_label_boxes",
    "render_gt_panel",
    "write_qa_split_report",
]
