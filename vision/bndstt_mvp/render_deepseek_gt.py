"""Render DeepSeek JSON boxes on current_origin.jpg for human QA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1/deepseek_annotation"
COLORS = {0: (0, 0, 255), 1: (0, 220, 70), 2: (255, 130, 0)}
NAMES = {0: "ball", 1: "hand", 2: "racket"}


def read_image(path: Path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"cannot read image: {path}")
    return image


def write_image(path: Path, image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok:
        raise RuntimeError(f"cannot encode image: {path}")
    path.write_bytes(encoded.tobytes())


def render(package: Path, json_path: Path, output_path: Path) -> None:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    packet_id = payload["packet_id"]
    image = read_image(package / "packets" / packet_id / "current_origin.jpg")
    for obj in payload.get("objects", []):
        class_id = int(obj["class_id"])
        x1, y1, x2, y2 = (round(float(value)) for value in obj["bbox_xyxy"])
        color = COLORS[class_id]
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
        text = f"{class_id} {NAMES[class_id]} [{obj.get('confidence_in_annotation', '?')}]"
        cv2.putText(image, text, (x1, max(24, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(image, text, (x1, max(24, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
    header = f"{packet_id} | status={payload.get('status')} | uncertain={payload.get('uncertain_objects', [])}"
    cv2.rectangle(image, (0, 0), (image.shape[1], 42), (0, 0, 0), -1)
    cv2.putText(image, header, (12, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    write_image(output_path, image)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("json", type=Path, nargs="+")
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for json_path in args.json:
        target = args.output_dir / f"{json_path.stem}.jpg"
        render(args.package.resolve(), json_path.resolve(), target.resolve())
        print(target)


if __name__ == "__main__":
    main()
