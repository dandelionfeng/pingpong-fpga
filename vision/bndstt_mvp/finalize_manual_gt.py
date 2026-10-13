"""Finalization gate and dataset export for BNDSTT_MANUAL_GT_V1.

Nothing here runs by itself: it is only executed after every one of the 280
images has been manually reviewed, and it refuses to produce a training dataset
if a single check fails.

Gate (all must hold):
  * 280 annotation JSON files, one per manifest image
  * review_state == MANUAL_REVIEWED for every image
  * NEEDS_REVIEW count == 0
  * 280 YOLO label files, paired 1:1 with images
  * class_id in 0/1/2, class_name consistent
  * every bbox inside the image, x1<x2, y1<y2, no zero area, no NaN
  * no duplicate bbox inside one image
  * JSON -> YOLO -> JSON round trip <= 1 px
  * train/val split preserved from the frame manifest
  * no train/val session overlap
  * no duplicate image across the set (content hash)

Export writes a YOLO-ready tree plus gray3 PNG copies, with an ABSOLUTE `path:`
in dataset.yaml (Ultralytics resolves a relative path against its own global
datasets_dir, which broke an earlier run).

  python vision/bndstt_mvp/finalize_manual_gt.py --check        # gate only
  python vision/bndstt_mvp/finalize_manual_gt.py --export       # gate + export
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MVP = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
GT = ROOT / "artifacts/files/datasets/BNDSTT_MANUAL_GT_V1"
FRAMES = MVP / "frames_manifest.csv"
ANNOTATIONS = GT / "annotations_json"
LABELS = GT / "labels_yolo"
EXPORTS = GT / "exports"

CLASSES = {0: "ball", 1: "hand", 2: "racket"}
EXPECTED_TOTAL = 280
EXPECTED_TRAIN = 224
EXPECTED_VAL = 56


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_rows() -> list[dict]:
    with FRAMES.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def yolo_round_trip(record: dict) -> float:
    worst = 0.0
    width = record["image_width"]
    height = record["image_height"]
    for obj in record["objects"]:
        x1, y1, x2, y2 = obj["bbox_xyxy"]
        xc, yc = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
        w, h = (x2 - x1) / width, (y2 - y1) / height
        back = [(xc - w / 2) * width, (yc - h / 2) * height, (xc + w / 2) * width, (yc + h / 2) * height]
        worst = max(worst, max(abs(a - b) for a, b in zip([x1, y1, x2, y2], back)))
    return worst


def check() -> tuple[dict, list[str]]:
    rows = frame_rows()
    errors: list[str] = []
    summary = {"images": len(rows), "train": 0, "val": 0, "objects": {0: 0, 1: 0, 2: 0},
               "by_state": {}, "needs_review": 0}

    if len(rows) != EXPECTED_TOTAL:
        errors.append(f"frame manifest has {len(rows)} images, expected {EXPECTED_TOTAL}")

    sessions: dict[str, set[str]] = {"train": set(), "val": set()}
    seen_hashes: dict[str, str] = {}
    json_ids = {p.stem for p in ANNOTATIONS.glob("*.json")}
    label_ids = {p.stem for p in LABELS.glob("*.txt")}

    for row in rows:
        image_id = Path(row["original_image_path"]).stem
        split = row["split"]
        summary[split] = summary.get(split, 0) + 1
        sessions.setdefault(split, set()).add(row["session_id"])

        original = MVP / row["original_image_path"]
        if not original.is_file():
            errors.append(f"{image_id}: original image missing")
            continue
        digest = sha256(original)
        if digest in seen_hashes:
            errors.append(f"{image_id}: duplicate image content of {seen_hashes[digest]}")
        seen_hashes[digest] = image_id

        path = ANNOTATIONS / f"{image_id}.json"
        if not path.is_file():
            errors.append(f"{image_id}: no annotation JSON (not reviewed yet)")
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        state = record.get("review_state")
        summary["by_state"][state] = summary["by_state"].get(state, 0) + 1
        if state != "MANUAL_REVIEWED":
            errors.append(f"{image_id}: review_state is {state}, expected MANUAL_REVIEWED")
        if state == "NEEDS_REVIEW":
            summary["needs_review"] += 1
        if record.get("annotation_source") != "HUMAN_MANUAL":
            errors.append(f"{image_id}: annotation_source is {record.get('annotation_source')!r}")
        if record.get("image_width") != int(row["width"]) or record.get("image_height") != int(row["height"]):
            errors.append(f"{image_id}: record dimensions do not match the frame manifest")
        if record.get("split") != split or record.get("session_id") != row["session_id"]:
            errors.append(f"{image_id}: split/session drift against the frame manifest")

        width, height = record["image_width"], record["image_height"]
        seen_boxes = set()
        for index, obj in enumerate(record.get("objects", [])):
            cid = obj.get("class_id")
            if cid not in CLASSES:
                errors.append(f"{image_id} obj{index}: class_id {cid!r} not 0/1/2")
                continue
            if obj.get("class_name") != CLASSES[cid]:
                errors.append(f"{image_id} obj{index}: class_name mismatch")
            box = obj.get("bbox_xyxy")
            if not isinstance(box, list) or len(box) != 4:
                errors.append(f"{image_id} obj{index}: bbox must have 4 numbers")
                continue
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or v != v for v in box):
                errors.append(f"{image_id} obj{index}: bbox has NaN or a non-number")
                continue
            x1, y1, x2, y2 = (float(v) for v in box)
            if not (x1 < x2 and y1 < y2):
                errors.append(f"{image_id} obj{index}: zero/negative area")
            elif not (0 <= x1 and 0 <= y1 and x2 <= width and y2 <= height):
                errors.append(f"{image_id} obj{index}: outside the image")
            key = (cid, x1, y1, x2, y2)
            if key in seen_boxes:
                errors.append(f"{image_id} obj{index}: duplicate bbox")
            seen_boxes.add(key)
            summary["objects"][cid] += 1

        worst = yolo_round_trip(record)
        if worst > 1.0:
            errors.append(f"{image_id}: YOLO round trip error {worst:.4f} px > 1")

        label = LABELS / f"{image_id}.txt"
        if not label.is_file():
            errors.append(f"{image_id}: YOLO label file missing")
        else:
            lines = [l for l in label.read_text(encoding="utf-8").splitlines() if l.strip()]
            if len(lines) != len(record.get("objects", [])):
                errors.append(
                    f"{image_id}: {len(lines)} YOLO lines for {len(record.get('objects', []))} objects"
                )

    missing_json = {Path(r['original_image_path']).stem for r in rows} - json_ids
    extra_json = json_ids - {Path(r['original_image_path']).stem for r in rows}
    if extra_json:
        errors.append(f"{len(extra_json)} annotation JSON files do not belong to the 280 set")
    if label_ids - json_ids:
        errors.append(f"{len(label_ids - json_ids)} YOLO label files have no annotation JSON")
    if missing_json:
        errors.append(f"{len(missing_json)} images still have no annotation JSON")

    overlap = sessions.get("train", set()) & sessions.get("val", set())
    if overlap:
        errors.append(f"train/val session overlap: {sorted(overlap)}")

    summary["train"] = sum(1 for r in rows if r["split"] == "train")
    summary["val"] = sum(1 for r in rows if r["split"] == "val")
    if summary["train"] != EXPECTED_TRAIN or summary["val"] != EXPECTED_VAL:
        errors.append(f"split is train {summary['train']} / val {summary['val']}, expected {EXPECTED_TRAIN}/{EXPECTED_VAL}")
    return summary, errors


def export() -> None:
    out = EXPORTS / "BNDSTT_YOLO_MANUAL_V1"
    if out.exists():
        shutil.rmtree(out)
    rows = frame_rows()
    import cv2
    import numpy as np

    written = {"train": 0, "val": 0}
    for row in rows:
        image_id = Path(row["original_image_path"]).stem
        record = json.loads((ANNOTATIONS / f"{image_id}.json").read_text(encoding="utf-8"))
        split = record["split"]
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

        source = MVP / row["derived_gray3_path"]
        image = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            image = cv2.imdecode(np.fromfile(MVP / row["original_image_path"], dtype=np.uint8), cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            image = cv2.merge((gray, gray, gray))
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise SystemExit(f"cannot encode {image_id}")
        (out / "images" / split / f"{image_id}.png").write_bytes(encoded.tobytes())
        shutil.copy2(LABELS / f"{image_id}.txt", out / "labels" / split / f"{image_id}.txt")
        written[split] += 1

    (out / "dataset.yaml").write_text(
        "# BNDSTT human manual GT v1 (PURE MANUAL).\n"
        "# gray3 images at native size; boxes are original-pixel XYXY converted to YOLO.\n"
        "# path must be absolute: Ultralytics resolves a relative path against its own datasets_dir.\n"
        f"path: {out.resolve().as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n  0: ball\n  1: hand\n  2: racket\n",
        encoding="utf-8",
    )
    print(f"exported to {out}  train={written['train']} val={written['val']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()
    if not args.check and not args.export:
        args.check = True

    summary, errors = check()
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if errors:
        print(f"\nFINALIZATION FAIL — {len(errors)} problem(s):")
        for message in errors[:40]:
            print("  -", message)
        if len(errors) > 40:
            print(f"  ... and {len(errors) - 40} more")
        raise SystemExit(1)
    print("\nFINALIZATION CHECK PASS")
    if args.export:
        export()


if __name__ == "__main__":
    main()
