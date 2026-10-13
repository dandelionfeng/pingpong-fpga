"""Small localhost-only bbox annotator for the ignored BNDSTT MVP task package."""

from __future__ import annotations

import json
import mimetypes
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts/files/datasets/BNDSTT_MVP_v1"
PROPOSALS_PATH = DATASET / "proposals/proposals.json"
REVIEWS_PATH = DATASET / "annotation_reviews.json"
SELECTION_PATH = DATASET / "manual_selection.csv"
GT_LABELS = DATASET / "gt_labels"
HTML_PATH = Path(__file__).with_name("annotator.html")


def load_document() -> dict:
    proposals = {
        item["derived_gray3_path"]: item
        for item in json.loads(PROPOSALS_PATH.read_text(encoding="utf-8"))["items"]
    }
    reviews = json.loads(REVIEWS_PATH.read_text(encoding="utf-8")) if REVIEWS_PATH.exists() else {}
    with SELECTION_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        items = list(csv.DictReader(handle))
    for index, item in enumerate(items):
        item["index"] = index
        item["width"] = int(item["width"])
        item["height"] = int(item["height"])
        item["frame_index"] = int(item["frame_index"])
        item["timestamp_seconds"] = float(item["timestamp_seconds"])
        item["proposals"] = proposals.get(item["derived_gray3_path"], {}).get("proposals", [])
        review = reviews.get(item["derived_gray3_path"])
        item["review"] = review if (review or {}).get("status") in {
            "REVIEWED_MANUAL", "UNCERTAIN_BALL", "PENDING"
        } else None
    counts = {status: 0 for status in ("REVIEWED_MANUAL", "UNCERTAIN_BALL", "PENDING")}
    for item in items:
        status = (item.get("review") or {}).get("status")
        if status in counts:
            counts[status] += 1
    return {"items": items, "counts": counts, "total": len(items)}


def save_review(payload: dict) -> None:
    document = load_document()
    index = int(payload["index"])
    if index < 0 or index >= len(document["items"]):
        raise ValueError("index out of range")
    item = document["items"][index]
    width, height = int(item["width"]), int(item["height"])
    boxes = []
    yolo_lines = []
    for raw in payload.get("boxes", []):
        class_id = int(raw["class_id"])
        if class_id not in (0, 1, 2):
            raise ValueError("class id must be 0, 1, or 2")
        x1, y1, x2, y2 = [float(v) for v in raw["xyxy"]]
        x1, x2 = sorted((max(0.0, min(width, x1)), max(0.0, min(width, x2))))
        y1, y2 = sorted((max(0.0, min(height, y1)), max(0.0, min(height, y2))))
        if x2 - x1 < 1 or y2 - y1 < 1:
            raise ValueError("box must have positive area")
        boxes.append({"class_id": class_id, "xyxy": [x1, y1, x2, y2]})
        xc, yc = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
        bw, bh = (x2 - x1) / width, (y2 - y1) / height
        yolo_lines.append(f"{class_id} {xc:.8f} {yc:.8f} {bw:.8f} {bh:.8f}")

    status = payload.get("status", "PENDING")
    if status not in ("REVIEWED_MANUAL", "UNCERTAIN_BALL", "PENDING"):
        raise ValueError("invalid manual review status")
    if status == "REVIEWED_MANUAL" and not payload.get("ball_checked", False):
        raise ValueError("ball visibility must be explicitly checked")
    review = {
        "status": status,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "codex_agent_manual_visual",
        "boxes": boxes,
        "ball_checked": bool(payload.get("ball_checked", False)),
        "note": payload.get("note", ""),
    }
    reviews = json.loads(REVIEWS_PATH.read_text(encoding="utf-8")) if REVIEWS_PATH.exists() else {}
    reviews[item["derived_gray3_path"]] = review
    REVIEWS_PATH.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")
    label_path = GT_LABELS / item["split"] / (Path(item["derived_gray3_path"]).stem + ".txt")
    if status == "REVIEWED_MANUAL":
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(("\n".join(yolo_lines) + "\n") if yolo_lines else "", encoding="utf-8")
    elif label_path.exists():
        label_path.unlink()


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_bytes(HTML_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/items":
            self.send_bytes(json.dumps(load_document(), ensure_ascii=False).encode(), "application/json")
            return
        if parsed.path.startswith("/file/"):
            relative = unquote(parsed.path[len("/file/"):])
            target = (DATASET / relative).resolve()
            if DATASET.resolve() not in target.parents or not target.is_file():
                self.send_bytes(b"not found", "text/plain", 404)
                return
            self.send_bytes(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            return
        self.send_bytes(b"not found", "text/plain", 404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/save":
            self.send_bytes(b"not found", "text/plain", 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            save_review(payload)
            self.send_bytes(b'{"ok":true}', "application/json")
        except Exception as exc:  # pragma: no cover - interactive error path
            self.send_bytes(json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json", 400)

    def log_message(self, fmt: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("BNDSTT MVP annotator: http://127.0.0.1:8765", flush=True)
    server.serve_forever()
