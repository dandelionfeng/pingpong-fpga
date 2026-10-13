"""Build per-source full-resolution origin/crop panels for manual GT review."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
OUT = ROOT / "artifacts/files/bndstt_mvp_work/manual_review_panels"
COLORS = ((0, 0, 255), (0, 220, 70), (255, 130, 0))
NAMES = ("ball", "hand", "racket")


def read_image(path: Path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def put(image: np.ndarray, text: str, xy: tuple[int, int], scale: float = 0.65) -> None:
    cv2.putText(image, text, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(image, text, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def main() -> None:
    with (DATASET / "manual_selection.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    proposal_items = {
        item["derived_gray3_path"]: item
        for item in json.loads((DATASET / "proposals/proposals.json").read_text(encoding="utf-8"))["items"]
    }
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["source_id"], []).append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for number, (source_id, source_rows) in enumerate(sorted(grouped.items()), 1):
        strips = []
        for row in sorted(source_rows, key=lambda value: float(value["fraction"])):
            origin = read_image(DATASET / row["original_image_path"])
            crop = read_image(DATASET / row["crop_reference_path"])
            h, w = origin.shape[:2]
            for x in range(0, w, 100):
                cv2.line(origin, (x, 0), (x, h), (120, 120, 120), 1)
                put(origin, str(x), (x + 3, 24), 0.5)
            for y in range(0, h, 100):
                cv2.line(origin, (0, y), (w, y), (120, 120, 120), 1)
                put(origin, str(y), (3, y + 18), 0.5)
            for box in proposal_items[row["derived_gray3_path"]].get("proposals", []):
                cls = int(box["class_id"])
                x1, y1, x2, y2 = (round(float(value)) for value in box["xyxy"])
                cv2.rectangle(origin, (x1, y1), (x2, y2), COLORS[cls], 3)
                put(origin, f"P {NAMES[cls]}", (x1, max(22, y1 - 5)), 0.65)
            target_w = 960
            target_h = 1080
            scale = min(target_w / crop.shape[1], target_h / crop.shape[0])
            resized = cv2.resize(crop, (round(crop.shape[1] * scale), round(crop.shape[0] * scale)))
            crop_canvas = np.full((target_h, target_w, 3), 18, np.uint8)
            y0 = (target_h - resized.shape[0]) // 2
            x0 = (target_w - resized.shape[1]) // 2
            crop_canvas[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized
            header = f"{row['split']}  {row['stage_hint']}  p={row['fraction']}  origin f={row['frame_index']}"
            put(origin, header, (330, 52), 0.85)
            put(crop_canvas, "CROP REFERENCE ONLY", (20, 40), 0.8)
            strips.append(np.hstack((origin, crop_canvas)))
        panel = np.vstack(strips)
        target = OUT / f"source_{number:02d}.jpg"
        encoded, buffer = cv2.imencode(".jpg", panel, [cv2.IMWRITE_JPEG_QUALITY, 92])
        target.write_bytes(buffer.tobytes())
        index_rows.append({"panel": target.as_posix(), "source_id": source_id, "rows": source_rows})
    (OUT / "index.json").write_text(json.dumps(index_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(index_rows)} panels to {OUT}")


if __name__ == "__main__":
    main()
