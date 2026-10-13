"""Five-packet fixture-only smoke test for DeepSeek JSON import and rendering."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from import_deepseek_labels import DEFAULT_PACKAGE, run
from render_deepseek_gt import render


def main() -> None:
    package = DEFAULT_PACKAGE
    smoke = package / "smoke_test"
    fixture_outputs = smoke / "fixture_outputs"
    converted = smoke / "converted_fixture_labels"
    previews = smoke / "fixture_previews"
    for path in (fixture_outputs, converted, previews):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)

    with (package / "manifests/mvp_v1_packets.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))[:5]
    fixture_manifest = smoke / "fixture_manifest.csv"
    with fixture_manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    objects_by_index = [
        [{"class_id": 0, "class_name": "ball", "bbox_xyxy": [20, 20, 32, 32], "confidence_in_annotation": "high"}],
        [{"class_id": 1, "class_name": "hand", "bbox_xyxy": [100, 100, 155, 160], "confidence_in_annotation": "high"}],
        [{"class_id": 2, "class_name": "racket", "bbox_xyxy": [220, 180, 290, 270], "confidence_in_annotation": "medium"}],
        [
            {"class_id": 0, "class_name": "ball", "bbox_xyxy": [40, 40, 52, 52], "confidence_in_annotation": "high"},
            {"class_id": 1, "class_name": "hand", "bbox_xyxy": [120, 130, 175, 190], "confidence_in_annotation": "high"},
            {"class_id": 2, "class_name": "racket", "bbox_xyxy": [260, 210, 335, 305], "confidence_in_annotation": "high"}
        ],
        [],
    ]
    for index, row in enumerate(rows):
        metadata = json.loads((package / "packets" / row["packet_id"] / "metadata.json").read_text(encoding="utf-8"))
        payload = {
            "packet_id": row["packet_id"],
            "image_width": metadata["origin_width"],
            "image_height": metadata["origin_height"],
            "status": "reviewed",
            "objects": objects_by_index[index],
            "uncertain_objects": ["ball"] if index == 4 else [],
            "notes": "PIPELINE FIXTURE ONLY — boxes are synthetic and are not Ground Truth."
        }
        output_path = fixture_outputs / f"{row['packet_id']}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        render(package, output_path, previews / f"{row['packet_id']}.jpg")

    report = run(package, fixture_outputs, converted, fixture_manifest, update_manifest=False)
    expected = {"accepted_gt": 4, "needs_manual_review": 1, "rejected": 0, "missing": 0}
    passed = report["counts"] == expected and len(list(previews.glob("*.jpg"))) == 5
    result = {
        "passed": passed,
        "fixture_only": True,
        "official_outputs_touched": False,
        "packets_tested": 5,
        "expected": expected,
        "actual": report["counts"],
        "preview_count": len(list(previews.glob("*.jpg"))),
    }
    (smoke / "smoke_test_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
