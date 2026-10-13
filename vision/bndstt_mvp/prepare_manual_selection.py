"""Build the REVIEWED_MANUAL candidate list and paired crop reference images.

Crop images are visual references only.  All saved boxes stay in the origin-frame
coordinate system and only origin gray3 images can enter the training package.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
BNDSTT = ROOT / "artifacts/files/datasets/BNDSTT"
MAPPING = ROOT / "reports/bndstt_origin_crop_mapping.csv"
SELECTION = DATASET / "manual_selection.csv"
REFERENCES = DATASET / "crop_references"

# Four complementary samples per source.  Source index rotation prevents a
# single fixed set of temporal positions from dominating the MVP.
PATTERNS = (
    {0.08, 0.20, 0.47, 0.74},
    {0.20, 0.33, 0.60, 0.88},
    {0.08, 0.33, 0.47, 0.74},
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    frames = read_csv(DATASET / "frames_manifest.csv")
    mapping = {row["source_id"]: row for row in read_csv(MAPPING)}
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in frames:
        grouped.setdefault(row["source_id"], []).append(row)

    selected: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    for source_index, source_id in enumerate(sorted(grouped)):
        match = mapping.get(source_id)
        reliable = bool(
            match
            and match.get("origin_exists", "").lower() == "true"
            and match.get("crop_exists", "").lower() == "true"
            and match.get("relation") == "paired"
            and match.get("match_confidence") == "high"
        )
        if not reliable:
            excluded.extend(grouped[source_id])
            continue
        wanted = PATTERNS[source_index % len(PATTERNS)]
        for row in grouped[source_id]:
            if round(float(row["fraction"]), 2) not in wanted:
                continue
            image_name = Path(row["derived_gray3_path"]).name
            reference_rel = Path("crop_references") / row["split"] / image_name
            selected.append(
                {
                    **row,
                    "crop_video_path": match["crop_path"],
                    "crop_reference_path": reference_rel.as_posix(),
                    "manual_status": "UNREVIEWED",
                }
            )

    REFERENCES.mkdir(parents=True, exist_ok=True)
    captures: dict[str, cv2.VideoCapture] = {}
    try:
        for index, row in enumerate(selected, 1):
            crop_rel = row["crop_video_path"]
            capture = captures.get(crop_rel)
            if capture is None:
                capture = cv2.VideoCapture(str(BNDSTT / crop_rel))
                if not capture.isOpened():
                    raise RuntimeError(f"cannot open crop reference: {crop_rel}")
                captures[crop_rel] = capture
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_index = min(frame_count - 1, max(0, round(float(row["fraction"]) * (frame_count - 1))))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, image = capture.read()
            if not ok:
                raise RuntimeError(f"cannot decode crop frame {frame_index}: {crop_rel}")
            target = DATASET / row["crop_reference_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            encoded, buffer = cv2.imencode(".png", image)
            if not encoded:
                raise RuntimeError(f"cannot encode crop reference: {target}")
            target.write_bytes(buffer.tobytes())
            row["crop_frame_index"] = str(frame_index)
            row["crop_width"] = str(image.shape[1])
            row["crop_height"] = str(image.shape[0])
            if index % 25 == 0:
                print(f"prepared {index}/{len(selected)} crop references", flush=True)
    finally:
        for capture in captures.values():
            capture.release()

    fields = list(selected[0])
    with SELECTION.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    summary = {
        "selected_images": len(selected),
        "selected_sources": len({row["source_id"] for row in selected}),
        "selected_sessions": len({row["session_id"] for row in selected}),
        "excluded_images_unreliable_pair": len(excluded),
        "selection_status": "UNREVIEWED",
        "crop_policy": "visual reference only; never GT coordinates",
    }
    (DATASET / "manual_selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
