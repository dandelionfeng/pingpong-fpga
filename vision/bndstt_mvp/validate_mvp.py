"""Validation and prediction previews for the BNDSTT YOLOv8n MVP (READ ONLY weights).

Runs best.pt over the 6 held-out val images: prints/records overall and per-class
P/R/mAP50/mAP50-95, and writes prediction previews next to the ground-truth
previews so the two can be compared by eye.

  python vision/bndstt_mvp/validate_mvp.py --weights <best.pt> --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/files/datasets/BNDSTT_YOLO_MVP_V1"
NAMES = {0: "ball", 1: "hand", 2: "racket"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--conf", type=float, default=0.20)
    ap.add_argument("--iou", type=float, default=0.50)
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    import torch
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    if not args.weights.is_file():
        raise SystemExit(f"missing weights: {args.weights}")
    args.out.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(args.weights))
    metrics = model.val(
        data=str(DATASET / "dataset.yaml"),
        split="val",
        imgsz=640,
        batch=8,
        device=args.device,
        plots=True,
        project=str(args.out.parent),
        name=args.out.name + "_val",
        exist_ok=True,
        verbose=True,
    )
    box = metrics.box
    payload = {
        "scope": "PROTOTYPE / MVP; metrics are preliminary and statistically unstable",
        "val_images": 6,
        "val_instances": 20,
        "weights": str(args.weights),
        "weights_sha256": sha256(args.weights),
        "thresholds": {"conf": args.conf, "iou": args.iou, "imgsz": 640},
        "overall": {
            "precision": float(box.mp),
            "recall": float(box.mr),
            "map50": float(box.map50),
            "map50_95": float(box.map),
        },
        "per_class": {
            NAMES[i]: {
                "precision": float(box.p[i]),
                "recall": float(box.r[i]),
                "map50": float(box.ap50[i]),
                "map50_95": float(box.ap[i]),
                "instances": int(box.np if hasattr(box, "np") else 0),
            }
            for i in NAMES
        },
    }
    (args.out / "validation_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    preview = args.out / "val_predictions"
    if preview.exists():
        shutil.rmtree(preview)
    preview.mkdir(parents=True)
    for image_path in sorted((DATASET / "images/val").glob("*.png")):
        result = model.predict(
            source=str(image_path), imgsz=640, conf=args.conf, iou=args.iou, device=args.device, verbose=False
        )[0]
        ok, encoded = cv2.imencode(".jpg", result.plot(), [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise SystemExit(f"cannot encode preview for {image_path}")
        (preview / f"{image_path.stem}.jpg").write_bytes(encoded.tobytes())

    print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
