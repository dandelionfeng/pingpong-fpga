"""Validate DeepSeek packet JSON and convert accepted annotations to YOLO labels."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1/deepseek_annotation"
CLASS_NAMES = {0: "ball", 1: "hand", 2: "racket"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}


def read_manifest(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def validate(payload: object, metadata: dict, packet_id: str) -> tuple[str, list[str], list[str]]:
    errors: list[str] = []
    review_reasons: list[str] = []
    if not isinstance(payload, dict):
        return "rejected", ["root must be a JSON object"], []
    required = {"packet_id", "image_width", "image_height", "status", "objects", "uncertain_objects", "notes"}
    missing = sorted(required - payload.keys())
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if payload.get("packet_id") != packet_id:
        errors.append("packet_id mismatch")
    width, height = metadata["origin_width"], metadata["origin_height"]
    if payload.get("image_width") != width or payload.get("image_height") != height:
        errors.append("image dimensions mismatch metadata")
    if payload.get("status") != "reviewed":
        errors.append("status must equal reviewed")
    uncertain = payload.get("uncertain_objects", [])
    if not isinstance(uncertain, list) or any(value not in CLASS_NAMES.values() for value in uncertain):
        errors.append("uncertain_objects contains invalid class name")
    elif uncertain:
        review_reasons.append("uncertain_objects is non-empty")
    objects = payload.get("objects", [])
    if not isinstance(objects, list):
        errors.append("objects must be an array")
        objects = []
    if not objects:
        review_reasons.append("empty annotation result")
    normalized: list[str] = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for index, obj in enumerate(objects):
        prefix = f"objects[{index}]"
        if not isinstance(obj, dict):
            errors.append(f"{prefix} must be an object")
            continue
        class_id = obj.get("class_id")
        if class_id not in CLASS_NAMES:
            errors.append(f"{prefix}.class_id must be 0/1/2")
            continue
        if obj.get("class_name") != CLASS_NAMES[class_id]:
            errors.append(f"{prefix}.class_name does not match class_id")
        confidence = obj.get("confidence_in_annotation")
        if confidence not in ALLOWED_CONFIDENCE:
            errors.append(f"{prefix}.confidence_in_annotation is invalid")
        elif confidence == "low":
            review_reasons.append(f"{prefix} has low confidence")
        bbox = obj.get("bbox_xyxy")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
            errors.append(f"{prefix}.bbox_xyxy must contain four finite numbers")
            continue
        x1, y1, x2, y2 = map(float, bbox)
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            errors.append(f"{prefix}.bbox_xyxy is out of bounds or has non-positive size")
            continue
        key = (class_id, round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3))
        if key in seen:
            errors.append(f"{prefix} duplicates an earlier bbox")
            continue
        seen.add(key)
        area_ratio = (x2 - x1) * (y2 - y1) / (width * height)
        if area_ratio > 0.60 or (class_id == 0 and area_ratio > 0.10):
            review_reasons.append(f"{prefix} has extreme bbox area ratio {area_ratio:.4f}")
        xc, yc = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
        bw, bh = (x2 - x1) / width, (y2 - y1) / height
        normalized.append(f"{class_id} {xc:.8f} {yc:.8f} {bw:.8f} {bh:.8f}")
    if errors:
        return "rejected", errors + review_reasons, []
    if review_reasons:
        return "needs_manual_review", review_reasons, []
    return "accepted_gt", [], normalized


def run(package: Path, outputs: Path, labels: Path, manifest_path: Path, update_manifest: bool) -> dict:
    rows, fields = read_manifest(manifest_path)
    results = []
    counts = {"accepted_gt": 0, "needs_manual_review": 0, "rejected": 0, "missing": 0}
    for row in rows:
        packet_id = row["packet_id"]
        output_path = outputs / f"{packet_id}.json"
        if not output_path.exists():
            counts["missing"] += 1
            continue
        metadata = json.loads((package / "packets" / packet_id / "metadata.json").read_text(encoding="utf-8"))
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception as exc:
            status, details, yolo = "rejected", [f"invalid JSON: {exc}"], []
        else:
            status, details, yolo = validate(payload, metadata, packet_id)
        counts[status] += 1
        if status == "accepted_gt":
            target = labels / row["split"] / f"{packet_id}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(yolo) + "\n", encoding="utf-8")
        results.append({"packet_id": packet_id, "status": status, "details": details})
        if update_manifest:
            row["status"] = status
    if update_manifest:
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    report = {"counts": counts, "results": results, "labels_root": str(labels)}
    report_path = labels.parent / "import_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--outputs", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--update-manifest", action="store_true")
    args = parser.parse_args()
    package = args.package.resolve()
    outputs = (args.outputs or package / "outputs").resolve()
    labels = (args.labels or package / "imported_yolo_labels").resolve()
    manifest = (args.manifest or package / "manifests/mvp_v1_packets.csv").resolve()
    report = run(package, outputs, labels, manifest, args.update_manifest)
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
