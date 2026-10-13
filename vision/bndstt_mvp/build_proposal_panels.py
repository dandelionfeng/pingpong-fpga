"""Build one seven-frame review panel per source from review-only proposals."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
OUT = ROOT / "artifacts/files/bndstt_mvp_work/proposal_panels"
COLORS = {0: "#ff3030", 1: "#20d850", 2: "#208cff"}
NAMES = {0: "ball", 1: "hand", 2: "racket"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    items = json.loads((DATASET / "proposals/proposals.json").read_text(encoding="utf-8"))["items"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[item["source_id"]].append(item)
    font = ImageFont.truetype("arial.ttf", 18)
    small = ImageFont.truetype("arial.ttf", 15)
    index_rows = []
    for source_index, (source_id, frames) in enumerate(groups.items(), 1):
        frames.sort(key=lambda item: item["timestamp_seconds"])
        panel = Image.new("RGB", (1920, 2320), "#11151b")
        draw_panel = ImageDraw.Draw(panel)
        for i, item in enumerate(frames):
            image = Image.open(DATASET / item["original_image_path"]).convert("RGB")
            image.thumbnail((960, 540), Image.Resampling.LANCZOS)
            x0 = (i % 2) * 960
            y0 = (i // 2) * 580 + 40
            scale = image.width / item["width"]
            d = ImageDraw.Draw(image)
            for box in item["proposals"]:
                class_id = int(box["class_id"])
                x1, y1, x2, y2 = [v * scale for v in box["xyxy"]]
                d.rectangle((x1, y1, x2, y2), outline=COLORS[class_id], width=3)
                d.text((x1 + 2, max(0, y1 - 18)), f"{class_id} {NAMES[class_id]}", fill=COLORS[class_id], font=small, stroke_width=2, stroke_fill="black")
            panel.paste(image, (x0, y0))
            draw_panel.text((x0 + 8, y0 - 30), f"#{i + 1} frame={item['frame_index']} t={item['timestamp_seconds']:.3f}s proposals={len(item['proposals'])}", fill="white", font=font)
        draw_panel.text((8, 8), f"source {source_index:02d}/40  {source_id}", fill="white", font=font)
        output = OUT / f"source_{source_index:02d}.jpg"
        panel.save(output, quality=94, subsampling=0)
        index_rows.append({"source_index": source_index, "source_id": source_id, "panel": str(output.relative_to(ROOT)).replace("\\", "/")})
    (OUT.parent / "proposal_panel_index.json").write_text(json.dumps(index_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated {len(index_rows)} panels in {OUT}")


if __name__ == "__main__":
    main()

