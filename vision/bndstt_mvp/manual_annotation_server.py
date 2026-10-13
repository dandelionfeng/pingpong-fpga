"""PURE MANUAL annotation server for BNDSTT_MANUAL_GT_V1.

This tool does **not** propose, suggest, or pre-fill any box. The first time an
image is opened the canvas is empty. The only boxes it will ever show are boxes
that a human saved through this same tool.

It deliberately does not read any prior label source: no DeepSeek outputs, no
ChatGPT curated GT, no proposals, no pose/skin/template/candidate boxes, no model
predictions. `AUTO_PROPOSALS_DISABLED` is enforced in code and surfaced in the UI.

Canonical data
--------------
* bbox space: ORIGINAL current_origin pixel XYXY (1920x1080 or the real size)
* annotations_json/<image_id>.json   canonical record, annotation_source=HUMAN_MANUAL
* labels_yolo/<image_id>.txt         normalized YOLO, regenerated on every save
* history/<image_id>/<ts>.json       every previous version, never overwritten
* manifests/manual_annotation_manifest.csv   progress, resumable after a crash
* manifests/checkpoint_<n>.csv       a snapshot every 20 reviewed images

Run:
  .\\.venv\\c-detector\\Scripts\\python.exe vision\\bndstt_mvp\\manual_annotation_server.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
MVP = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
FRAMES = MVP / "frames_manifest.csv"
CROPS = MVP / "crop_references"
GT = ROOT / "artifacts/files/datasets/BNDSTT_MANUAL_GT_V1"
WEB = Path(__file__).resolve().parent / "manual_web"

ANNOTATIONS = GT / "annotations_json"
LABELS = GT / "labels_yolo"
MANIFESTS = GT / "manifests"
HISTORY = GT / "history"
QA = GT / "qa"
EXPORTS = GT / "exports"
MANIFEST = MANIFESTS / "manual_annotation_manifest.csv"

CLASSES = {0: "ball", 1: "hand", 2: "racket"}
CLASS_IDS = {v: k for k, v in CLASSES.items()}
STATES = ("UNLABELED", "MANUAL_IN_PROGRESS", "MANUAL_REVIEWED", "NEEDS_REVIEW")
CHECKPOINT_EVERY = 20

# A crop reference may be PNG bytes with a .jpg extension, so both are probed.
CROP_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

AUTO_PROPOSALS_DISABLED = True

_lock = threading.Lock()


# --------------------------------------------------------------------------- io


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then replace atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_frames() -> list[dict]:
    with FRAMES.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    # A deterministic, split-grouped order so progress is easy to follow.
    rows.sort(key=lambda r: (r["split"] != "train", r["session_id"], int(r["frame_index"])))
    for index, row in enumerate(rows):
        row["image_id"] = Path(row["original_image_path"]).stem
        row["prev_path"] = ""
        row["next_path"] = ""
        row["crop_reference_path"] = ""
        row["manifest_index"] = index
    by_session: dict[str, list[dict]] = {}
    for row in rows:
        by_session.setdefault(row["session_id"], []).append(row)
    for group in by_session.values():
        group.sort(key=lambda r: int(r["frame_index"]))
        for i, row in enumerate(group):
            if i > 0:
                row["prev_path"] = group[i - 1]["original_image_path"]
            if i + 1 < len(group):
                row["next_path"] = group[i + 1]["original_image_path"]
    for row in rows:
        for suffix in CROP_SUFFIXES:
            candidate = CROPS / row["split"] / f"{row['image_id']}{suffix}"
            if candidate.is_file():
                row["crop_reference_path"] = str(candidate.relative_to(MVP)).replace("\\", "/")
                break
    return rows


FRAMES_ROWS = load_frames()
FRAME_BY_ID = {row["image_id"]: row for row in FRAMES_ROWS}


# ------------------------------------------------------------------ annotations


def annotation_path(image_id: str) -> Path:
    return ANNOTATIONS / f"{image_id}.json"


def label_path(image_id: str) -> Path:
    return LABELS / f"{image_id}.txt"


def load_annotation(image_id: str) -> dict | None:
    path = annotation_path(image_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build_record(row: dict, objects: list[dict], review_state: str) -> dict:
    width = int(row["width"])
    height = int(row["height"])
    # Only a reviewed state may be persisted. UNLABELED and MANUAL_IN_PROGRESS are
    # transient UI states and must never reach disk as a saved annotation.
    if review_state not in ("MANUAL_REVIEWED", "NEEDS_REVIEW"):
        raise ValueError(f"review_state {review_state!r} cannot be saved")
    clean = []
    for obj in objects:
        class_id = int(obj["class_id"])
        if class_id not in CLASSES:
            raise ValueError(f"class_id {class_id} is not 0/1/2")
        x1, y1, x2, y2 = (round(float(v), 2) for v in obj["bbox_xyxy"])
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError(f"bbox {[x1, y1, x2, y2]} is outside {width}x{height} or degenerate")
        clean.append(
            {"class_id": class_id, "class_name": CLASSES[class_id], "bbox_xyxy": [x1, y1, x2, y2]}
        )
    return {
        "image_id": row["image_id"],
        "image_path": row["original_image_path"],
        "split": row["split"],
        "session_id": row["session_id"],
        "source_id": row["source_id"],
        "frame_index": int(row["frame_index"]),
        "image_width": width,
        "image_height": height,
        "review_state": review_state,
        "annotation_source": "HUMAN_MANUAL",
        "objects": clean,
        "gray3_path": row["derived_gray3_path"],
        "yolo_label_path": row["yolo_label_path"],
    }


def yolo_lines(record: dict) -> list[str]:
    width = record["image_width"]
    height = record["image_height"]
    lines = []
    for obj in record["objects"]:
        x1, y1, x2, y2 = obj["bbox_xyxy"]
        xc = (x1 + x2) / 2 / width
        yc = (y1 + y2) / 2 / height
        w = (x2 - x1) / width
        h = (y2 - y1) / height
        lines.append(f"{obj['class_id']} {xc:.8f} {yc:.8f} {w:.8f} {h:.8f}")
    return lines


def round_trip_error(record: dict) -> float:
    """Max pixel error of pixel -> YOLO -> pixel over every box."""
    worst = 0.0
    width = record["image_width"]
    height = record["image_height"]
    for obj in record["objects"]:
        x1, y1, x2, y2 = obj["bbox_xyxy"]
        xc = (x1 + x2) / 2 / width
        yc = (y1 + y2) / 2 / height
        w = (x2 - x1) / width
        h = (y2 - y1) / height
        back = [
            (xc - w / 2) * width,
            (yc - h / 2) * height,
            (xc + w / 2) * width,
            (yc + h / 2) * height,
        ]
        worst = max(worst, max(abs(a - b) for a, b in zip([x1, y1, x2, y2], back)))
    return worst


def save_annotation(image_id: str, objects: list[dict], review_state: str) -> dict:
    """Validate, archive the previous version, write atomically, write YOLO."""
    row = FRAME_BY_ID.get(image_id)
    if row is None:
        raise KeyError(f"unknown image_id {image_id}")
    if review_state not in STATES or review_state == "UNLABELED":
        raise ValueError(f"review_state {review_state} is not a saved state")

    record = build_record(row, objects, review_state)
    worst = round_trip_error(record)
    if worst > 1.0:
        raise ValueError(f"JSON->YOLO->JSON round trip error {worst:.4f} px exceeds 1 px")

    with _lock:
        existing = annotation_path(image_id)
        if existing.is_file():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            hist = HISTORY / image_id
            hist.mkdir(parents=True, exist_ok=True)
            (hist / f"{stamp}.json").write_text(existing.read_text(encoding="utf-8"), encoding="utf-8")
        atomic_write_text(annotation_path(image_id), json.dumps(record, ensure_ascii=False, indent=1) + "\n")
        lines = yolo_lines(record)
        atomic_write_text(label_path(image_id), ("\n".join(lines) + "\n") if lines else "")
        rewrite_manifest()

    # Hand back what is actually on disk, so the client renders the saved truth.
    saved = load_annotation(image_id)
    assert saved is not None
    return {"record": saved, "round_trip_error": worst, "yolo_lines": lines}


def mark_in_progress(image_id: str) -> None:
    with _lock:
        row = FRAME_BY_ID[image_id]
        state = status_of(image_id)
        if state == "UNLABELED":
            rewrite_manifest({image_id: "MANUAL_IN_PROGRESS"})
            _ = row


def status_of(image_id: str) -> str:
    record = load_annotation(image_id)
    if record and record.get("review_state") in STATES:
        return record["review_state"]
    return "UNLABELED"


def manifest_rows(overrides: dict[str, str] | None = None) -> list[dict]:
    overrides = overrides or {}
    rows = []
    for row in FRAMES_ROWS:
        image_id = row["image_id"]
        record = load_annotation(image_id)
        state = overrides.get(image_id)
        if state is None:
            state = record["review_state"] if record else "UNLABELED"
        counts = {0: 0, 1: 0, 2: 0}
        if record:
            for obj in record["objects"]:
                counts[obj["class_id"]] += 1
        mtime = ""
        path = annotation_path(image_id)
        if path.is_file():
            mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(
            {
                "image_id": image_id,
                "split": row["split"],
                "session_id": row["session_id"],
                "source_id": row["source_id"],
                "frame_index": row["frame_index"],
                "image_path": row["original_image_path"],
                "prev_path": row["prev_path"],
                "next_path": row["next_path"],
                "crop_reference_path": row["crop_reference_path"],
                "review_state": state,
                "num_ball": counts[0],
                "num_hand": counts[1],
                "num_racket": counts[2],
                "annotation_json": f"annotations_json/{image_id}.json" if record else "",
                "yolo_label": f"labels_yolo/{image_id}.txt" if record else "",
                "last_modified": mtime,
            }
        )
    return rows


MANIFEST_FIELDS = [
    "image_id", "split", "session_id", "source_id", "frame_index",
    "image_path", "prev_path", "next_path", "crop_reference_path",
    "review_state", "num_ball", "num_hand", "num_racket",
    "annotation_json", "yolo_label", "last_modified",
]


def rewrite_manifest(overrides: dict[str, str] | None = None) -> list[dict]:
    rows = manifest_rows(overrides)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    buffer = [",".join(MANIFEST_FIELDS)]
    for row in rows:
        buffer.append(",".join('"' + str(row[f]) + '"' for f in MANIFEST_FIELDS))
    atomic_write_text(MANIFEST, "\n".join(buffer) + "\n")
    reviewed = sum(1 for r in rows if r["review_state"] == "MANUAL_REVIEWED")
    if reviewed and reviewed % CHECKPOINT_EVERY == 0:
        checkpoint = MANIFESTS / f"checkpoint_{reviewed:03d}.csv"
        if not checkpoint.exists():
            atomic_write_text(checkpoint, "\n".join(buffer) + "\n")
    return rows


def stats() -> dict:
    rows = manifest_rows()
    by_state = {s: 0 for s in STATES}
    counts = {0: 0, 1: 0, 2: 0}
    split_counts = {
        "train": {"images": 0, "reviewed": 0, 0: 0, 1: 0, 2: 0},
        "val": {"images": 0, "reviewed": 0, 0: 0, 1: 0, 2: 0},
    }
    for row in rows:
        by_state[row["review_state"]] = by_state.get(row["review_state"], 0) + 1
        split_counts[row["split"]]["images"] += 1
        if row["review_state"] == "MANUAL_REVIEWED":
            split_counts[row["split"]]["reviewed"] += 1
        for cid in (0, 1, 2):
            value = int(row[{"0": "num_ball", "1": "num_hand", "2": "num_racket"}[str(cid)]])
            counts[cid] += value
            split_counts[row["split"]][cid] += value
    return {
        "total": len(rows),
        "by_state": by_state,
        "reviewed": by_state.get("MANUAL_REVIEWED", 0),
        "needs_review": by_state.get("NEEDS_REVIEW", 0),
        "remaining": len(rows) - by_state.get("MANUAL_REVIEWED", 0),
        "objects": {"ball": counts[0], "hand": counts[1], "racket": counts[2]},
        "split": split_counts,
        "auto_proposals_disabled": AUTO_PROPOSALS_DISABLED,
        "manifest": str(MANIFEST.relative_to(GT)),
    }


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------- server


SAFE_IMAGE_ROOTS = ("images_color", "images_gray3", "crop_references")


class Handler(BaseHTTPRequestHandler):
    server_version = "ManualAnnotation/1.0"

    def log_message(self, fmt, *args):  # keep the console readable
        if "/api/state" in (self.path or ""):
            return
        super().log_message(fmt, *args)

    # -- helpers ----------------------------------------------------------
    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _bytes(self, data: bytes, content_type: str, cache: bool = True) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # -- routing ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route in ("/", "/index.html"):
                return self._serve_static("index.html", "text/html; charset=utf-8")
            if route == "/api/state":
                return self._json(
                    {
                        "ok": True,
                        "classes": [{"id": i, "name": CLASSES[i]} for i in sorted(CLASSES)],
                        "states": list(STATES),
                        "stats": stats(),
                        "frames": [
                            {
                                "image_id": r["image_id"],
                                "index": r["manifest_index"],
                                "split": r["split"],
                                "session_id": r["session_id"],
                                "source_id": r["source_id"],
                                "frame_index": r["frame_index"],
                                "stage_hint": r["stage_hint"],
                                "width": int(r["width"]),
                                "height": int(r["height"]),
                                "image_path": r["original_image_path"],
                                "gray3_path": r["derived_gray3_path"],
                                "prev_path": r["prev_path"],
                                "next_path": r["next_path"],
                                "crop_reference_path": r["crop_reference_path"],
                                "review_state": status_of(r["image_id"]),
                                "auto_proposals_disabled": AUTO_PROPOSALS_DISABLED,
                            }
                            for r in FRAMES_ROWS
                        ],
                    }
                )
            if route == "/api/annotation":
                image_id = parse_qs(parsed.query).get("image_id", [""])[0]
                if image_id not in FRAME_BY_ID:
                    return self._error("unknown image_id", 404)
                return self._json({"ok": True, "record": load_annotation(image_id)})
            if route.startswith("/media/"):
                return self._serve_media(route[len("/media/"):])
            if route.startswith("/static/"):
                name = route[len("/static/"):]
                content_type = "text/javascript" if name.endswith(".mjs") else "text/css" if name.endswith(".css") else "application/octet-stream"
                return self._serve_static(name, content_type)
            if route == "/api/stats":
                return self._json({"ok": True, "stats": stats()})
            return self._error("not found", 404)
        except Exception as exc:  # surface the reason rather than a blank 500
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/save":
                payload = self._read_json()
                image_id = payload.get("image_id", "")
                objects = payload.get("objects", [])
                state = payload.get("review_state", "MANUAL_REVIEWED")
                try:
                    result = save_annotation(image_id, objects, state)
                except (KeyError, ValueError) as exc:
                    return self._error(str(exc), 400)
                return self._json({"ok": True, **result, "stats": stats()})
            if parsed.path == "/api/in_progress":
                payload = self._read_json()
                image_id = payload.get("image_id", "")
                if image_id not in FRAME_BY_ID:
                    return self._error("unknown image_id", 404)
                mark_in_progress(image_id)
                return self._json({"ok": True, "stats": stats()})
            if parsed.path == "/api/qa_flag":
                payload = self._read_json()
                image_id = payload.get("image_id", "")
                flag = payload.get("flag", "PASS")
                if image_id not in FRAME_BY_ID:
                    return self._error("unknown image_id", 404)
                QA.mkdir(parents=True, exist_ok=True)
                log = QA / "qa_review.csv"
                if not log.exists():
                    atomic_write_text(log, "timestamp,image_id,flag\n")
                with log.open("a", encoding="utf-8", newline="") as stream:
                    stream.write(f"{datetime.now().isoformat(timespec='seconds')},{image_id},{flag}\n")
                return self._json({"ok": True})
            return self._error("not found", 404)
        except Exception as exc:
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    # -- static / media ---------------------------------------------------
    def _serve_static(self, name: str, content_type: str) -> None:
        target = (WEB / name).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.is_file():
            return self._error("not found", 404)
        return self._bytes(target.read_bytes(), content_type)

    def _serve_media(self, relative: str) -> None:
        # Only files under the three allowed image roots may ever be served, so a
        # crafted path cannot read arbitrary files on disk.
        candidate = (MVP / relative).resolve()
        try:
            inside = candidate.relative_to(MVP.resolve())
        except ValueError:
            return self._error("forbidden", 403)
        if not inside.parts or inside.parts[0] not in SAFE_IMAGE_ROOTS:
            return self._error("forbidden", 403)
        if not candidate.is_file():
            return self._error("not found", 404)
        data = candidate.read_bytes()
        # Sniff the real format: crop references are PNG bytes named .jpg.
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            content_type = "image/png"
        elif data[:3] == b"\xff\xd8\xff":
            content_type = "image/jpeg"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            content_type = "image/webp"
        else:
            content_type = "application/octet-stream"
        return self._bytes(data, content_type)


def ensure_dirs() -> None:
    for directory in (ANNOTATIONS, LABELS, MANIFESTS, HISTORY, QA, EXPORTS):
        directory.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--find-port", action="store_true", help="try the next ports if busy")
    args = parser.parse_args()

    ensure_dirs()
    rewrite_manifest()
    current = stats()
    print(f"images            : {current['total']} (train {current['split']['train']['images']} / val {current['split']['val']['images']})")
    print(f"already reviewed  : {current['reviewed']}")
    print(f"needs review      : {current['needs_review']}")
    print("auto proposals    : DISABLED (manual GT only; no legacy label is loaded)")

    port = args.port
    attempts = 20 if args.find_port else 1
    server = None
    for offset in range(attempts):
        candidate = port + offset
        try:
            server = ThreadingHTTPServer((args.host, candidate), Handler)
            port = candidate
            break
        except OSError as exc:
            print(f"port {candidate} unavailable: {exc}")
    if server is None:
        raise SystemExit("no free port found")

    url = f"http://{args.host}:{port}"
    print(f"\nMANUAL ANNOTATION TOOL READY\n  open: {url}\n  root: {GT.relative_to(ROOT)}")
    print("  press Ctrl+C to stop (progress is already on disk; just relaunch to resume)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
