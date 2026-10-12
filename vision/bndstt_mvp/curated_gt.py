"""Curated GT import, schema validation, gray3 dataset build and QA render (READ ONLY source).

Only the 29 packets listed in `chatgpt_curated_gt_v1/curated_manifest.csv` are ever
read. The old DeepSeek `deepseek_annotation/` tree is never globbed, so no legacy
label, proposal or auto box can leak into the MVP dataset.

Subcommands
-----------
  validate   schema + count gate for the 29 curated JSON files
  qa         render each curated bbox back onto current_origin.jpg for visual QA
  build      build the gray3 YOLO dataset (images/labels/dataset.yaml)
  roundtrip  convert YOLO txt back to pixel boxes and render on gray3

  python curated_gt.py validate
  python curated_gt.py qa --out-dir artifacts/runs/bndstt_yolov8n_mvp_v1/qa
  python curated_gt.py build --out artifacts/files/datasets/BNDSTT_YOLO_MVP_V1
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1/chatgpt_curated_gt_v1"
# Frame images are the curated packets' own copies; the originals live in the
# DeepSeek packet tree only as raw frames, NOT as labels.
FRAME_ROOT = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1/deepseek_annotation/packets"
CLASS_NAMES = {0: "ball", 1: "hand", 2: "racket"}
EXPECTED_TOTAL = {0: 27, 1: 41, 2: 11}
EXPECTED_SPLIT = {
    "train": {"images": 23, 0: 21, 1: 31, 2: 7},
    "val": {"images": 6, 0: 6, 1: 10, 2: 4},
}
COLORS = {0: (255, 40, 40), 1: (40, 255, 80), 2: (255, 170, 0)}


def read_manifest() -> list[dict]:
    with (PKG / "curated_manifest.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def frame_path(packet_id: str) -> Path:
    return FRAME_ROOT / packet_id / "current_origin.jpg"


def load_gt(packet_id: str) -> dict:
    return json.loads((PKG / "outputs" / f"{packet_id}.json").read_text(encoding="utf-8"))


def validate_records() -> tuple[dict, list[dict], list[str]]:
    rows = read_manifest()
    by_split = {"train": {"images": 0, 0: 0, 1: 0, 2: 0}, "val": {"images": 0, 0: 0, 1: 0, 2: 0}}
    totals = {0: 0, 1: 0, 2: 0}
    records = []
    errors: list[str] = []

    for row in rows:
        pid = row["packet_id"]
        split = row["split"]
        path = PKG / "outputs" / f"{pid}.json"
        if not path.exists():
            errors.append(f"{pid}: missing output json")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("packet_id") != pid:
            errors.append(f"{pid}: packet_id mismatch")
        if payload.get("image_width") != 1920 or payload.get("image_height") != 1080:
            errors.append(f"{pid}: image dimensions are not 1920x1080")
        if payload.get("status") != "reviewed":
            errors.append(f"{pid}: status is {payload.get('status')!r}, expected 'reviewed'")
        if payload.get("uncertain_objects"):
            errors.append(f"{pid}: uncertain_objects is not empty: {payload['uncertain_objects']}")
        if not frame_path(pid).exists():
            errors.append(f"{pid}: frame image missing at {frame_path(pid)}")

        seen = set()
        counts = {0: 0, 1: 0, 2: 0}
        for i, obj in enumerate(payload.get("objects", [])):
            try:
                cid, (x1, y1, x2, y2) = validate_object(obj, pid, i)
            except RuntimeError as exc:
                errors.append(str(exc))
                continue
            key = (cid, x1, y1, x2, y2)
            if key in seen:
                errors.append(f"{pid} objects[{i}]: duplicate bbox")
            seen.add(key)
            counts[cid] += 1
            totals[cid] += 1

        if counts != {0: int(row["ball"]), 1: int(row["hand"]), 2: int(row["racket"])}:
            errors.append(
                f"{pid}: per-class counts {counts} disagree with manifest "
                f"({row['ball']}/{row['hand']}/{row['racket']})"
            )

        by_split[split]["images"] += 1
        for cid in (0, 1, 2):
            by_split[split][cid] += counts[cid]
        records.append({"packet_id": pid, "split": split, "counts": counts})

    for split, expected in EXPECTED_SPLIT.items():
        got = by_split[split]
        if got["images"] != expected["images"]:
            errors.append(f"{split}: {got['images']} images, expected {expected['images']}")
        for cid in (0, 1, 2):
            if got[cid] != expected[cid]:
                errors.append(
                    f"{split}: class {CLASS_NAMES[cid]} {got[cid]}, expected {expected[cid]}"
                )
    for cid, want in EXPECTED_TOTAL.items():
        if totals[cid] != want:
            errors.append(f"total class {CLASS_NAMES[cid]} {totals[cid]}, expected {want}")

    summary = {"images": len(records), "by_split": by_split, "totals": totals}
    return summary, records, errors


def validate_object(obj: object, packet_id: str, index: int) -> tuple[int, tuple[float, float, float, float]]:
    """Validate one annotation object and return (class_id, (x1, y1, x2, y2)).

    Raises RuntimeError with a specific reason so a bad GT file is never silently
    accepted into the MVP dataset.
    """
    if not isinstance(obj, dict):
        raise RuntimeError(f"{packet_id} object {index}: not a mapping")
    class_id = obj.get("class_id")
    if class_id not in CLASS_NAMES:
        raise RuntimeError(f"{packet_id} object {index}: class id {class_id!r} is not 0/1/2")
    if obj.get("class_name") != CLASS_NAMES[class_id]:
        raise RuntimeError(f"{packet_id} object {index}: class id/name mismatch")
    bbox = obj.get("bbox_xyxy")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise RuntimeError(f"{packet_id} object {index}: bbox_xyxy must have four numbers")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in bbox):
        raise RuntimeError(f"{packet_id} object {index}: bbox contains a non-number")
    x1, y1, x2, y2 = (float(v) for v in bbox)
    if any(v != v for v in (x1, y1, x2, y2)):
        raise RuntimeError(f"{packet_id} object {index}: bbox contains NaN")
    if not (x1 < x2 and y1 < y2):
        raise RuntimeError(f"{packet_id} object {index}: bbox must satisfy x1<x2 and y1<y2")
    if not (0 <= x1 and 0 <= y1 and x2 <= 1920 and y2 <= 1080):
        raise RuntimeError(f"{packet_id} object {index}: bbox outside 1920x1080")
    return int(class_id), (x1, y1, x2, y2)


def yolo_line(class_id: int, bbox: tuple[float, float, float, float]) -> str:
    """Convert one pixel XYXY box in 1920x1080 into a normalized YOLO line."""
    x1, y1, x2, y2 = bbox
    return (
        f"{int(class_id)} "
        f"{(x1 + x2) / 2 / 1920:.8f} {(y1 + y2) / 2 / 1080:.8f} "
        f"{(x2 - x1) / 1920:.8f} {(y2 - y1) / 1080:.8f}"
    )


def yolo_lines(objects: list[dict]) -> list[str]:
    return [yolo_line(cid, box) for cid, box in (validate_object(o, "?", i) for i, o in enumerate(objects))]


def to_gray3(src: Path, dst: Path) -> tuple[int, int]:
    """Grayscale then replicate to R==G==B, saved losslessly at native size."""
    import cv2
    import numpy as np

    img = cv2.imdecode(np.fromfile(src, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot decode {src}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    assert np.array_equal(gray3[:, :, 0], gray3[:, :, 1]) and np.array_equal(gray3[:, :, 1], gray3[:, :, 2])
    dst.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", gray3)
    if not ok:
        raise RuntimeError(f"cannot encode {dst}")
    dst.write_bytes(encoded.tobytes())
    return gray3.shape[1], gray3.shape[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("qa")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--source", choices=["color", "gray3"], default="color")
    p.add_argument("--scale", type=float, default=1.0)
    p.set_defaults(func=cmd_qa)

    p = sub.add_parser("build")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("roundtrip")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.set_defaults(func=cmd_roundtrip)

    args = ap.parse_args()
    args.func(args)


def cmd_validate(args: argparse.Namespace) -> None:
    summary, records, errors = validate_records()
    print(json.dumps(summary, indent=1))
    if errors:
        print("\nERRORS:")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)
    print("\nVALIDATE PASS: all schema and count gates satisfied")


def _draw(img, boxes, scale=1.0):
    import cv2

    for cid, (x1, y1, x2, y2), label in boxes:
        p1 = (int(round(x1 * scale)), int(round(y1 * scale)))
        p2 = (int(round(x2 * scale)), int(round(y2 * scale)))
        cv2.rectangle(img, p1, p2, COLORS[cid], 2)
        if label:
            cv2.putText(img, label, (p1[0], max(14, p1[1] - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, label, (p1[0], max(14, p1[1] - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS[cid], 1, cv2.LINE_AA)
    return img


def cmd_qa(args: argparse.Namespace) -> None:
    import cv2
    import numpy as np

    summary, records, errors = validate_records()
    if errors:
        raise SystemExit("validate failed; run `validate` first")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for rec in records:
        pid = rec["packet_id"]
        payload = load_gt(pid)
        src = frame_path(pid)
        img = cv2.imdecode(np.fromfile(src, dtype=np.uint8), cv2.IMREAD_COLOR)
        if args.source == "gray3":
            img = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        boxes = [
            (int(o["class_id"]), tuple(float(v) for v in o["bbox_xyxy"]), CLASS_NAMES[int(o["class_id"])])
            for o in payload["objects"]
        ]
        img = _draw(img, boxes, args.scale)
        header = f"{pid} split={rec['split']} ball={rec['counts'][0]} hand={rec['counts'][1]} racket={rec['counts'][2]}"
        cv2.rectangle(img, (0, 0), (img.shape[1], 34), (0, 0, 0), -1)
        cv2.putText(img, header, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        out = args.out_dir / f"{pid}.jpg"
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise RuntimeError(f"cannot encode {out}")
        out.write_bytes(enc.tobytes())
        print(out)


def cmd_build(args: argparse.Namespace) -> None:
    import numpy as np

    summary, records, errors = validate_records()
    if errors:
        print("VALIDATE FAILED:")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "images/train").mkdir(parents=True)
    (out / "images/val").mkdir(parents=True)
    (out / "labels/train").mkdir(parents=True)
    (out / "labels/val").mkdir(parents=True)

    written = {"train": 0, "val": 0}
    for rec in records:
        pid = rec["packet_id"]
        split = rec["split"]
        payload = load_gt(pid)
        img_name = f"{pid}.png"
        w, h = to_gray3(frame_path(pid), out / "images" / split / img_name)
        if (w, h) != (1920, 1080):
            raise SystemExit(f"{pid}: gray3 image is {w}x{h}, expected 1920x1080")
        lines = yolo_lines(payload["objects"])
        (out / "labels" / split / f"{pid}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        written[split] += 1

        # gray3 contract check: R == G == B
        import cv2

        check = cv2.imdecode(np.fromfile(out / "images" / split / img_name, dtype=np.uint8), cv2.IMREAD_COLOR)
        if not (np.array_equal(check[:, :, 0], check[:, :, 1]) and np.array_equal(check[:, :, 1], check[:, :, 2])):
            raise SystemExit(f"{pid}: gray3 channels differ")

    yaml_text = (
        "# BNDSTT YOLOv8n MVP v1 - PROTOTYPE, not a competition-final dataset.\n"
        f"# source GT: chatgpt_curated_gt_v1 (29 curated packets, train 23 / val 6)\n"
        "# gray3: grayscale replicated to R==G==B, native 1920x1080, no resize here.\n"
        "# path must be ABSOLUTE: Ultralytics resolves a relative 'path' against its own\n"
        "# global datasets_dir, which is not inside this repository.\n"
        f"path: {out.resolve().as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: ball\n"
        "  1: hand\n"
        "  2: racket\n"
    )
    (out / "dataset.yaml").write_text(yaml_text, encoding="utf-8")

    print(json.dumps({"written": written, "summary": summary}, indent=1))
    print(f"dataset: {out}")
    print(f"yaml: {out / 'dataset.yaml'}")


def cmd_roundtrip(args: argparse.Namespace) -> None:
    import cv2
    import numpy as np

    args.out_dir.mkdir(parents=True, exist_ok=True)
    mismatches = []
    n = 0
    for split in ("train", "val"):
        for label_file in sorted((args.dataset / "labels" / split).glob("*.txt")):
            pid = label_file.stem
            img_path = args.dataset / "images" / split / f"{pid}.png"
            img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
            h, w = img.shape[:2]
            boxes = []
            for line in label_file.read_text(encoding="utf-8").split():
                pass
            for line in label_file.read_text(encoding="utf-8").strip().splitlines():
                if not line.strip():
                    continue
                cid, xc, yc, bw, bh = line.split()
                cid = int(cid)
                xc, yc, bw, bh = (float(v) for v in (xc, yc, bw, bh))
                x1 = (xc - bw / 2) * w
                y1 = (yc - bh / 2) * h
                x2 = (xc + bw / 2) * w
                y2 = (yc + bh / 2) * h
                boxes.append((cid, (x1, y1, x2, y2), CLASS_NAMES[cid]))
            img = _draw(img, boxes, 1.0)
            out = args.out_dir / f"{split}_{pid}.jpg"
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            out.write_bytes(enc.tobytes())

            # numeric round trip against the source JSON
            payload = load_gt(pid)
            src = sorted((int(o["class_id"]), *[float(v) for v in o["bbox_xyxy"]]) for o in payload["objects"])
            rt = sorted((cid, x1, y1, x2, y2) for cid, (x1, y1, x2, y2), _ in boxes)
            for a, b in zip(src, rt):
                if a[0] != b[0] or max(abs(a[i + 1] - b[i + 1]) for i in range(4)) > 0.02:
                    mismatches.append((pid, a, b))
            n += 1
    print(f"round-trip images: {n}, mismatches: {len(mismatches)}")
    for m in mismatches[:10]:
        print("  ", m)
    if mismatches:
        raise SystemExit("ROUND TRIP FAILED")
    print("ROUND TRIP PASS")


if __name__ == "__main__":
    main()
