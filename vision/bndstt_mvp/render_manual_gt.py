"""QA contact sheets for BNDSTT_MANUAL_GT_V1 (READ ONLY).

Renders saved human boxes back onto the original current_origin frames. Contact
sheets are for looking only: they never feed coordinates back, and nothing here
can modify an annotation.

  python vision/bndstt_mvp/render_manual_gt.py --recent 20
  python vision/bndstt_mvp/render_manual_gt.py --random 50 --seed 7
  python vision/bndstt_mvp/render_manual_gt.py --all
  python vision/bndstt_mvp/render_manual_gt.py --needs-review
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MVP = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
GT = ROOT / "artifacts/files/datasets/BNDSTT_MANUAL_GT_V1"
ANNOTATIONS = GT / "annotations_json"
QA = GT / "qa"

COLORS = {0: (255, 59, 48), 1: (40, 199, 111), 2: (255, 159, 10)}
NAMES = {0: "ball", 1: "hand", 2: "racket"}
TILE_W = 520
TILE_H = 320
COLS = 4


def records() -> list[dict]:
    out = []
    for path in sorted(ANNOTATIONS.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"warning: unreadable {path.name}")
    return out


def render_tile(record: dict) -> Image.Image:
    image = Image.open(MVP / record["image_path"]).convert("RGB")
    scale = TILE_W / image.width
    tile = image.resize((TILE_W, int(image.height * scale)), Image.LANCZOS)
    draw = ImageDraw.Draw(tile)
    for obj in record.get("objects", []):
        x1, y1, x2, y2 = obj["bbox_xyxy"]
        color = COLORS[obj["class_id"]]
        draw.rectangle([x1 * scale, y1 * scale, x2 * scale, y2 * scale], outline=color, width=2)
        cx, cy = (x1 + x2) / 2 * scale, (y1 + y2) / 2 * scale
        r = 9 if obj["class_id"] == 0 else 3
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
    header = (
        f"{record['image_id']}  {record['split']}  f{record['frame_index']}  "
        f"{record['review_state']}  b{sum(1 for o in record['objects'] if o['class_id'] == 0)}"
        f" h{sum(1 for o in record['objects'] if o['class_id'] == 1)}"
        f" r{sum(1 for o in record['objects'] if o['class_id'] == 2)}"
    )
    canvas = Image.new("RGB", (TILE_W, tile.height + 18), (14, 14, 18))
    canvas.paste(tile, (0, 18))
    ImageDraw.Draw(canvas).text((4, 3), header, fill=(255, 255, 0))
    return canvas


def build_sheet(selected: list[dict], out: Path) -> None:
    if not selected:
        print("nothing to render")
        return
    tiles = [render_tile(r) for r in selected]
    tile_h = max(t.height for t in tiles)
    rows = (len(tiles) + COLS - 1) // COLS
    sheet = Image.new("RGB", (TILE_W * COLS, tile_h * rows), (10, 10, 12))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % COLS) * TILE_W, (index // COLS) * tile_h))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=92)
    print(f"{out}  images={len(tiles)} size={sheet.size}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, default=0, help="most recently modified N")
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--needs-review", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    rows = records()
    if not rows:
        print("no annotations yet in", ANNOTATIONS)
        return

    if args.needs_review:
        selected = [r for r in rows if r["review_state"] == "NEEDS_REVIEW"]
        out = args.out or QA / "needs_review.jpg"
    elif args.random:
        rng = random.Random(args.seed)
        selected = rng.sample(rows, min(args.random, len(rows)))
        out = args.out or QA / f"random_{len(selected)}.jpg"
    elif args.all:
        selected = rows
        out = args.out or QA / "all.jpg"
    else:
        count = args.recent or 20
        ordered = sorted(rows, key=lambda r: (ANNOTATIONS / f"{r['image_id']}.json").stat().st_mtime, reverse=True)
        selected = ordered[:count]
        out = args.out or QA / f"recent_{len(selected)}.jpg"

    build_sheet(selected, out)


if __name__ == "__main__":
    main()
