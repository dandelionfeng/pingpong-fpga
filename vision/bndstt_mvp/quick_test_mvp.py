"""Held-out quick-test inference for the BNDSTT YOLOv8n MVP (READ ONLY).

Runs the trained best.pt over the FIVE frozen quick-test videos listed in
`BNDSTT_MVP_v1/split_manifest.csv` (split == quick_test). Those sessions are
disjoint from every train and val session, so they were never used for training,
validation, tuning or annotation.

Preprocessing matches the training contract exactly: BGR frame -> grayscale ->
three identical channels -> Ultralytics letterbox 640 (normalisation /255 happens
once, inside Ultralytics). Thresholds are FIXED before looking at any result:
conf = 0.20, iou = 0.50.

Outputs (annotated MP4, per-frame JSONL, mid-video preview, summary) go under an
ignored artifacts directory; no video is written into Git.

  python vision/bndstt_mvp/quick_test_mvp.py --weights <best.pt> --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1/split_manifest.csv"
SOURCE_ROOT = ROOT / "artifacts/files/datasets/BNDSTT"
NAMES = {0: "ball", 1: "hand", 2: "racket"}
CONF = 0.20
IOU = 0.50
IMGSZ = 640


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quick_rows() -> list[dict]:
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["split"] == "quick_test"]
    if len(rows) != 5:
        raise SystemExit(f"expected exactly 5 frozen quick-test videos, found {len(rows)}")
    return rows


def gray3(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.merge((gray, gray, gray))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    if not args.weights.is_file():
        raise SystemExit(f"missing weights: {args.weights}")
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite quick-test output: {args.out}")
    args.out.mkdir(parents=True)

    import torch
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")

    model = YOLO(str(args.weights))
    summaries = []

    for ordinal, row in enumerate(quick_rows(), start=1):
        source = SOURCE_ROOT / row["source_video_path"]
        if not source.is_file():
            raise SystemExit(f"quick-test source missing: {source}")
        digest = sha256(source)
        if digest != row["source_video_sha256"]:
            raise SystemExit(f"quick-test provenance mismatch for {source}")

        capture = cv2.VideoCapture(str(source))
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        stem = f"quick_{ordinal:02d}_{row['session_id']}"
        video_out = args.out / f"{stem}.mp4"
        writer = cv2.VideoWriter(str(video_out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not capture.isOpened() or not writer.isOpened():
            raise SystemExit(f"cannot open media for {source}")

        class_counts: Counter[str] = Counter()
        frames_with: Counter[str] = Counter()
        inference_ms: list[float] = []
        mid_preview = None
        index = 0

        with (args.out / f"{stem}.jsonl").open("w", encoding="utf-8") as records:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                result = model.predict(
                    source=gray3(frame), imgsz=IMGSZ, conf=CONF, iou=IOU, device=args.device, verbose=False
                )[0]
                detections = []
                seen = set()
                if result.boxes is not None and len(result.boxes):
                    xyxy = result.boxes.xyxy.detach().cpu().numpy()
                    confs = result.boxes.conf.detach().cpu().numpy()
                    clss = result.boxes.cls.detach().cpu().numpy().astype(int)
                    for box, conf, cid in zip(xyxy, confs, clss):
                        name = NAMES.get(int(cid), str(cid))
                        class_counts[name] += 1
                        seen.add(name)
                        detections.append(
                            {
                                "class": name,
                                "class_id": int(cid),
                                "confidence": round(float(conf), 4),
                                "bbox_xyxy": [round(float(v), 2) for v in box],
                            }
                        )
                frames_with.update(seen)
                records.write(
                    json.dumps(
                        {
                            "frame_idx": index,
                            "timestamp_ms": round(index * 1000.0 / fps, 2),
                            "detections": detections,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                rendered = result.plot()
                writer.write(rendered)
                if index == total // 2:
                    mid_preview = rendered
                inference_ms.append(float(result.speed["inference"]))
                index += 1

        capture.release()
        writer.release()
        if index != total:
            raise SystemExit(f"decoded {index}/{total} frames for {source}")
        if mid_preview is not None:
            ok, enc = cv2.imencode(".jpg", mid_preview)
            if ok:
                (args.out / f"{stem}_preview.jpg").write_bytes(enc.tobytes())

        summaries.append(
            {
                "ordinal": ordinal,
                "session_id": row["session_id"],
                "source_video_path": row["source_video_path"],
                "source_sha256": digest,
                "frames": index,
                "fps": round(fps, 3),
                "resolution": [width, height],
                "detections": dict(class_counts),
                "frames_with_detections": dict(frames_with),
                "mean_inference_ms": round(sum(inference_ms) / len(inference_ms), 2),
                "annotated_video": str(video_out),
                "frame_jsonl": str(args.out / f"{stem}.jsonl"),
            }
        )
        print(f"{stem}: frames={index} detections={dict(class_counts)} ms/frame={sum(inference_ms)/len(inference_ms):.1f}")

    (args.out / "summary.json").write_text(
        json.dumps(
            {
                "scope": "PROTOTYPE / MVP; qualitative only, no detection GT for these videos",
                "weights": str(args.weights),
                "weights_sha256": sha256(args.weights),
                "preprocessing": "BGR -> grayscale -> 3 identical channels -> letterbox 640; /255 once inside Ultralytics",
                "thresholds": {"conf": CONF, "iou": IOU, "imgsz": IMGSZ},
                "videos": summaries,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"summary: {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
