"""Audit the 280-frame manual annotation set before building the tool (READ ONLY).

Reports the numbers the annotation spec requires: totals, split, sessions,
train/val session overlap, duplicate image hashes, quick_test contamination, and
whether every referenced file actually exists.

  python vision/bndstt_mvp/audit_manual_set.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MVP = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
FRAMES = MVP / "frames_manifest.csv"
SPLIT = MVP / "split_manifest.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    with FRAMES.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with SPLIT.open("r", encoding="utf-8-sig", newline="") as fh:
        split_rows = list(csv.DictReader(fh))

    quick_sessions = {r["session_id"] for r in split_rows if r["split"] == "quick_test"}
    quick_videos = {r["source_video_path"] for r in split_rows if r["split"] == "quick_test"}

    by_split = Counter(r["split"] for r in rows)
    sessions_by_split: dict[str, set[str]] = defaultdict(set)
    sources_by_split: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        sessions_by_split[r["split"]].add(r["session_id"])
        sources_by_split[r["split"]].add(r["source_video_path"])

    overlap = sessions_by_split["train"] & sessions_by_split["val"]

    # quick_test contamination: a frame whose session or source video is frozen
    # as quick_test must never appear in this annotation set.
    contaminated = [
        r["original_image_path"]
        for r in rows
        if r["session_id"] in quick_sessions or r["source_video_path"] in quick_videos
    ]

    missing_original, missing_gray3, missing_crop = [], [], []
    hashes: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        original = MVP / r["original_image_path"]
        if not original.is_file():
            missing_original.append(r["original_image_path"])
        else:
            hashes[sha256(original)].append(r["original_image_path"])
        if not (MVP / r["derived_gray3_path"]).is_file():
            missing_gray3.append(r["derived_gray3_path"])

    duplicates = {h: paths for h, paths in hashes.items() if len(paths) > 1}

    # crop references are optional per frame and may be PNG bytes with any of
    # these extensions, so all of them are probed.
    crop_dir = MVP / "crop_references"
    crop_suffixes = (".png", ".jpg", ".jpeg", ".webp")
    with_crop = 0
    for r in rows:
        stem = Path(r["original_image_path"]).stem
        if any((crop_dir / r["split"] / f"{stem}{s}").exists() for s in crop_suffixes):
            with_crop += 1

    report = {
        "total_images": len(rows),
        "train": by_split.get("train", 0),
        "val": by_split.get("val", 0),
        "source_videos": len(sources_by_split["train"] | sources_by_split["val"]),
        "source_videos_train": len(sources_by_split["train"]),
        "source_videos_val": len(sources_by_split["val"]),
        "sessions": len(sessions_by_split["train"] | sessions_by_split["val"]),
        "sessions_train": len(sessions_by_split["train"]),
        "sessions_val": len(sessions_by_split["val"]),
        "train_val_session_overlap": sorted(overlap),
        "duplicate_image_groups": len(duplicates),
        "duplicate_images": duplicate_group_examples(duplicates),
        "quick_test_contamination": len(contaminated),
        "missing_original_images": missing_original,
        "missing_gray3_images": missing_gray3,
        "frames_with_crop_reference": with_crop,
        "annotation_status": dict(Counter(r["annotation_review_status"] for r in rows)),
    }

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {args.json_out}")

    ok = (
        len(rows) == 280
        and by_split.get("train") == 224
        and by_split.get("val") == 56
        and not overlap
        and not duplicates
        and not contaminated
        and not missing_original
    )
    print("\nAUDIT PASS" if ok else "\nAUDIT PROBLEMS FOUND")
    raise SystemExit(0 if ok else 1)


def duplicate_group_examples(duplicates: dict[str, list[str]], limit: int = 5) -> list[list[str]]:
    return [paths for paths in list(duplicates.values())[:limit]]


def _packet_for(original_image_path: str) -> str | None:
    """Map a frame file name back to its deepseek packet id when one exists.

    The frame naming is <session>__o<origin>__p<fraction>__f<frame>, and the packet
    manifest lists the same source_id, so the mapping is read from that manifest
    rather than guessed from the name.
    """
    return _PACKET_INDEX.get(original_image_path)


def _build_packet_index() -> dict[str, str]:
    index: dict[str, str] = {}
    manifest = MVP / "deepseek_annotation/manifests/mvp_v1_packets.csv"
    if not manifest.exists():
        return index
    with manifest.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            meta_path = MVP / "deepseek_annotation/packets" / row["packet_id"] / "metadata.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            rel = meta.get("origin_image_path")
            if rel:
                index[rel] = row["packet_id"]
    return index


_PACKET_INDEX = _build_packet_index()

if __name__ == "__main__":
    main()
