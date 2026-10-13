"""Prepare the 150-image MVP_DEEPSEEK_V1 annotation handoff package."""

from __future__ import annotations

import csv
import json
import random
import shutil
from pathlib import Path

import cv2


SEED = 20261011
TARGETS = {"train": 120, "val": 30}
ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
BNDSTT = ROOT / "artifacts/files/datasets/BNDSTT"
DEEPSEEK = DATASET / "deepseek_annotation"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_jpeg(path: Path, image) -> None:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError(f"cannot encode {path}")
    path.write_bytes(encoded.tobytes())


def seek_frame(capture: cv2.VideoCapture, index: int):
    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, image = capture.read()
    if not ok:
        raise RuntimeError(f"cannot decode frame {index}")
    return image


def main() -> None:
    candidates = read_csv(DATASET / "manual_selection.csv")
    split_rows = {row["source_id"]: row for row in read_csv(DATASET / "split_manifest.csv")}
    proposal_items = {
        item["derived_gray3_path"]: item
        for item in json.loads((DATASET / "proposals/proposals.json").read_text(encoding="utf-8"))["items"]
    }
    rng = random.Random(SEED)
    chosen: list[dict[str, str]] = []
    for split, target in TARGETS.items():
        pool = [row for row in candidates if row["split"] == split]
        rng.shuffle(pool)
        chosen.extend(pool[:target])
    chosen.sort(key=lambda row: (row["split"], row["session_id"], row["source_id"], float(row["fraction"])))

    for directory in ("packets", "images", "references", "outputs", "manifests", "tools", "smoke_test"):
        (DEEPSEEK / directory).mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    captures: dict[str, cv2.VideoCapture] = {}
    try:
        for serial, row in enumerate(chosen, 1):
            packet_id = f"MVPDS1_{row['split'].upper()}_{serial:04d}"
            packet = DEEPSEEK / "packets" / packet_id
            packet.mkdir(parents=True, exist_ok=True)
            source_rel = row["source_video_path"]
            capture = captures.get(source_rel)
            if capture is None:
                capture = cv2.VideoCapture(str(BNDSTT / source_rel))
                if not capture.isOpened():
                    raise RuntimeError(f"cannot open {source_rel}")
                captures[source_rel] = capture
            fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            current_index = int(row["frame_index"])
            offset = max(1, round(fps * 0.05))  # target ~50 ms, within requested 30-100 ms
            prev_index = max(0, current_index - offset)
            next_index = min(frame_count - 1, current_index + offset)
            prev_image = seek_frame(capture, prev_index)
            next_image = seek_frame(capture, next_index)
            current_target = packet / "current_origin.jpg"
            shutil.copy2(DATASET / row["original_image_path"], current_target)
            write_jpeg(packet / "prev_origin.jpg", prev_image)
            write_jpeg(packet / "next_origin.jpg", next_image)
            shutil.copy2(DATASET / row["crop_reference_path"], packet / "current_crop_reference.jpg")

            proposal = proposal_items.get(row["derived_gray3_path"], {"proposals": []})
            proposal_payload = {
                "warning": "SUGGESTION ONLY. Do not mechanically accept; known ball misses and racket false positives.",
                "packet_id": packet_id,
                "origin_coordinate_space": [int(row["width"]), int(row["height"])],
                "proposals": proposal.get("proposals", []),
            }
            (packet / "proposal_reference.json").write_text(
                json.dumps(proposal_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            source_meta = split_rows[row["source_id"]]
            metadata = {
                "packet_id": packet_id,
                "dataset_version": "MVP_DEEPSEEK_V1",
                "source_id": row["source_id"],
                "session_id": row["session_id"],
                "split": row["split"],
                "stage_hint": row["stage_hint"],
                "frame_index": current_index,
                "timestamp": float(row["timestamp_seconds"]),
                "origin_width": int(row["width"]),
                "origin_height": int(row["height"]),
                "origin_image_path": row["original_image_path"],
                "derived_gray3_path": row["derived_gray3_path"],
                "prev_frame_path": "prev_origin.jpg",
                "prev_frame_index": prev_index,
                "prev_timestamp": prev_index / fps,
                "next_frame_path": "next_origin.jpg",
                "next_frame_index": next_index,
                "next_timestamp": next_index / fps,
                "neighbor_offset_ms": offset / fps * 1000.0,
                "crop_reference_path": "current_crop_reference.jpg",
                "proposal_path": "proposal_reference.json",
                "source_video_path": source_rel,
                "spin_label": source_meta.get("spin_code", ""),
                "landing_label": source_meta.get("landing_code", ""),
                "coordinate_policy": "All bbox coordinates must refer to current_origin.jpg only.",
            }
            (packet / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            manifest_rows.append({
                "packet_id": packet_id,
                "split": row["split"],
                "session_id": row["session_id"],
                "source_id": row["source_id"],
                "stage_hint": row["stage_hint"],
                "frame_index": current_index,
                "timestamp": row["timestamp_seconds"],
                "origin_image": (packet / "current_origin.jpg").relative_to(DEEPSEEK).as_posix(),
                "prev_image": (packet / "prev_origin.jpg").relative_to(DEEPSEEK).as_posix(),
                "next_image": (packet / "next_origin.jpg").relative_to(DEEPSEEK).as_posix(),
                "crop_reference": (packet / "current_crop_reference.jpg").relative_to(DEEPSEEK).as_posix(),
                "proposal_reference": (packet / "proposal_reference.json").relative_to(DEEPSEEK).as_posix(),
                "deepseek_output": f"outputs/{packet_id}.json",
                "status": "pending",
            })
            if serial % 25 == 0:
                print(f"prepared {serial}/{len(chosen)} packets", flush=True)
    finally:
        for capture in captures.values():
            capture.release()

    fields = list(manifest_rows[0])
    manifest_path = DEEPSEEK / "manifests/mvp_v1_packets.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest_rows)
    summary = {
        "version": "MVP_DEEPSEEK_V1",
        "seed": SEED,
        "packets": len(manifest_rows),
        "split_counts": {split: sum(row["split"] == split for row in manifest_rows) for split in TARGETS},
        "sessions": len({row["session_id"] for row in manifest_rows}),
        "sources": len({row["source_id"] for row in manifest_rows}),
        "quick_test_packets": sum(row["split"] == "quick_test" for row in manifest_rows),
    }
    (DEEPSEEK / "manifests/mvp_v1_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
