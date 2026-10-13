r"""BR FINETUNE 标注服务：2 类（0 ball / 1 racket）轻量人工修正 UI。

用途
----
把 baseline ``best.pt`` 的 proposals 载入浏览器，让你只做四件事：
删除误框 / 移动框 / resize / 补漏框。保存后该图标记
``annotation_source = HUMAN_VERIFIED``。**只有 HUMAN_VERIFIED 才能进入训练。**

与旧标注器的关系
----------------
旧 ``vision/bndstt_mvp/manual_annotation_server.py`` 是 3 类（ball/hand/racket）
方案，本文件**不改动它**，只提供并行的 BR FINETUNE 模式（无 hand）。

启动
----
    .\.venv\c-detector\Scripts\python.exe vision\c_perception_v2\annotator_br.py --port 8899

然后浏览器打开 http://127.0.0.1:8899/
"""

from __future__ import annotations

import json
import mimetypes
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 同时支持两种用法：作为包导入与直接运行脚本（相对导入在两种情况下都成立）。
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path

    _PACKAGE_DIR = _Path(__file__).resolve().parent
    _VISION_DIR = _PACKAGE_DIR.parent
    _REPO_ROOT = _VISION_DIR.parent
    for _entry in (str(_REPO_ROOT), str(_VISION_DIR), str(_PACKAGE_DIR)):
        if _entry not in _sys.path:
            _sys.path.insert(0, _entry)
    __package__ = "c_perception_v2"
from .finetune_domain import (
    CLASS_NAMES_BR,
    FinetuneError,
    annotations_dir,
    finetune_dir,
    load_human_annotation,
    manifest_path,
    proposals_dir,
    read_csv_rows,
    review_progress,
    workspace_dir,
)

# 只允许这两类
ALLOWED_CLASSES = {0: "ball", 1: "racket"}
HOST = "127.0.0.1"
DEFAULT_PORT = 8899

_write_lock = threading.Lock()


# ================================================================ 数据访问
def pool_rows() -> list[dict]:
    return read_csv_rows(manifest_path())


def load_proposal(image_id: str) -> dict | None:
    path = proposals_dir() / (image_id + ".json")
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def image_path_for(image_id: str) -> Path | None:
    for candidate in (
        workspace_dir() / "images" / (image_id + ".jpg"),
        workspace_dir() / "images" / (image_id + ".png"),
    ):
        if candidate.is_file():
            return candidate
    for row in pool_rows():
        if row["image_id"] == image_id:
            path = Path(row["image_path"])
            if path.is_file():
                return path
    return None


def validate_payload(payload: dict) -> dict:
    """校验并规范化人工标注：只允许 ball/racket，框必须在图内。"""
    if not isinstance(payload, dict):
        raise FinetuneError("payload must be an object")
    image_id = str(payload.get("image_id", "")).strip()
    if not image_id:
        raise FinetuneError("image_id is required")
    width = int(payload.get("image_width") or 0)
    height = int(payload.get("image_height") or 0)
    if width <= 0 or height <= 0:
        raise FinetuneError("image_width/image_height are required")
    objects_in = payload.get("objects") or []
    objects: list[dict] = []
    for index, obj in enumerate(objects_in):
        try:
            class_id = int(obj.get("class_id"))
        except (TypeError, ValueError) as exc:
            raise FinetuneError("object " + str(index) + ": bad class_id") from exc
        if class_id not in ALLOWED_CLASSES:
            raise FinetuneError(
                "object " + str(index) + ": class_id " + str(class_id)
                + " not allowed (only 0 ball / 1 racket)"
            )
        try:
            x1, y1, x2, y2 = (float(v) for v in obj.get("bbox_xyxy"))
        except (TypeError, ValueError) as exc:
            raise FinetuneError("object " + str(index) + ": bad bbox_xyxy") from exc
        if x2 <= x1 or y2 <= y1:
            raise FinetuneError("object " + str(index) + ": zero/negative area box")
        if x1 < -1 or y1 < -1 or x2 > width + 1 or y2 > height + 1:
            raise FinetuneError(
                "object " + str(index) + ": bbox outside image "
                + str([x1, y1, x2, y2]) + " vs " + str(width) + "x" + str(height)
            )
        objects.append(
            {
                "class_id": class_id,
                "class_name": ALLOWED_CLASSES[class_id],
                "bbox_xyxy": [
                    round(max(0.0, x1), 3),
                    round(max(0.0, y1), 3),
                    round(min(float(width), x2), 3),
                    round(min(float(height), y2), 3),
                ],
            }
        )
    return {
        "image_id": image_id,
        "image_width": width,
        "image_height": height,
        "annotation_source": "HUMAN_VERIFIED",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reviewer": str(payload.get("reviewer") or "human"),
        "objects": objects,
    }


def save_annotation(payload: dict) -> dict:
    record = validate_payload(payload)
    annotations_dir().mkdir(parents=True, exist_ok=True)
    target = annotations_dir() / (record["image_id"] + ".json")
    temp = target.with_suffix(".json.tmp")
    with _write_lock:
        temp.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(target)
    return record


def delete_annotation(image_id: str) -> bool:
    target = annotations_dir() / (image_id + ".json")
    if target.is_file():
        target.unlink()
        return True
    return False


def build_queue() -> list[dict]:
    """待办队列：未确认优先；返回每张图的 proposals 与确认状态。"""
    progress = review_progress()
    verified = set(progress["verified_ids"])
    queue: list[dict] = []
    for index, row in enumerate(pool_rows()):
        image_id = row["image_id"]
        proposal = load_proposal(image_id)
        human = load_human_annotation(image_id)
        source = human if human is not None else proposal
        queue.append(
            {
                "index": index,
                "image_id": image_id,
                "stage_hint": row.get("stage_hint", ""),
                "session_id": row.get("session_id", ""),
                "source_id": row.get("source_id", ""),
                "has_existing_manual_gt": row.get("has_existing_manual_gt", "0") == "1",
                "verified": image_id in verified,
                "annotation_source": (source or {}).get("annotation_source", "NONE"),
                "objects": (source or {}).get("objects", []),
                "image_width": (source or {}).get("image_width"),
                "image_height": (source or {}).get("image_height"),
            }
        )
    return queue


# ================================================================ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "BRFinetuneAnnotator/1.0"

    def log_message(self, fmt, *args):  # 降噪
        return

    # --- 工具 ----------------------------------------------------------
    def _send_json(self, payload, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    # --- 路由 ----------------------------------------------------------
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                self._send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if route == "/api/queue":
                self._send_json({"queue": build_queue(), "progress": review_progress(),
                                 "classes": ALLOWED_CLASSES})
                return
            if route == "/api/progress":
                self._send_json(review_progress())
                return
            if route == "/api/image":
                image_id = (query.get("id") or [""])[0]
                path = image_path_for(image_id)
                if path is None:
                    self._send_json({"error": "image not found: " + image_id}, 404)
                    return
                content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                self._send_bytes(path.read_bytes(), content_type)
                return
            self._send_json({"error": "not found: " + route}, 404)
        except FinetuneError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": type(exc).__name__ + ": " + str(exc)}, 500)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/save":
                record = save_annotation(self._read_json())
                self._send_json(
                    {"ok": True, "saved": record, "progress": review_progress()}
                )
                return
            if parsed.path == "/api/delete":
                payload = self._read_json()
                removed = delete_annotation(str(payload.get("image_id", "")))
                self._send_json({"ok": True, "removed": removed, "progress": review_progress()})
                return
            if parsed.path == "/api/shutdown":
                self._send_json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._send_json({"error": "not found: " + parsed.path}, 404)
        except FinetuneError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": type(exc).__name__ + ": " + str(exc)}, 500)


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>BR FINETUNE 标注（ball / racket）</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
         background: #14161a; color: #e8eaed; display: flex; height: 100vh; }
  #left { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  #toolbar { padding: 8px 12px; background: #1d2026; border-bottom: 1px solid #2c313a;
             display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; }
  #canvasWrap { flex: 1; position: relative; overflow: hidden; background: #0b0c0f; }
  canvas { position: absolute; left: 0; top: 0; transform-origin: 0 0; cursor: crosshair; }
  #right { width: 330px; border-left: 1px solid #2c313a; background: #1a1d23;
           display: flex; flex-direction: column; font-size: 13px; }
  .panel { padding: 10px 12px; border-bottom: 1px solid #2c313a; }
  .row { display: flex; justify-content: space-between; gap: 8px; margin: 4px 0; }
  .muted { color: #9aa0a6; }
  button { background: #2b3038; color: #e8eaed; border: 1px solid #3a4048;
           border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 13px; }
  button:hover { background: #353b45; }
  button.primary { background: #1f6feb; border-color: #1f6feb; }
  button.primary:hover { background: #2d7ff9; }
  button.danger { background: #7d2b2b; border-color: #9b3535; }
  button.ghost { background: transparent; }
  #list { overflow-y: auto; flex: 1; }
  .item { padding: 6px 12px; border-bottom: 1px solid #23262d; cursor: pointer;
          display: flex; justify-content: space-between; gap: 6px; }
  .item:hover { background: #23262d; }
  .item.active { background: #1f6feb33; border-left: 3px solid #1f6feb; }
  .badge { border-radius: 4px; padding: 1px 6px; font-size: 11px; }
  .ok { background: #1b5e20; }
  .todo { background: #4a3b0f; }
  .ref { background: #3a2f5b; }
  code { background: #0d0f12; padding: 1px 5px; border-radius: 4px; }
</style>
</head>
<body>
<div id="left">
  <div id="toolbar">
    <button id="prev">◀ 上一张 (A)</button>
    <button id="next" class="primary">下一张 (D) ▶</button>
    <span class="muted">|</span>
    <button id="addBall">+ ball (1)</button>
    <button id="addRacket">+ racket (2)</button>
    <button id="delSel" class="danger">删除选中 (Del)</button>
    <span class="muted">|</span>
    <button id="save" class="primary">保存并下一张 (S / Enter)</button>
    <button id="reload" class="ghost">还原</button>
    <span class="muted">|</span>
    <button id="fit">适应窗口 (F)</button>
    <button id="zoomIn">放大 +</button>
    <button id="zoomOut">缩小 −</button>
    <span class="muted" id="zoomLabel">100%</span>
  </div>
  <div id="canvasWrap"><canvas id="cv"></canvas></div>
</div>
<div id="right">
  <div class="panel">
    <div class="row"><b id="title">载入中…</b></div>
    <div class="row"><span class="muted">阶段</span><span id="stage">-</span></div>
    <div class="row"><span class="muted">session</span><span id="session" style="font-size:11px">-</span></div>
    <div class="row"><span class="muted">source</span><span id="source" style="font-size:11px">-</span></div>
    <div class="row"><span class="muted">标注来源</span><span id="source_kind">-</span></div>
    <div class="row"><span class="muted">ball / racket</span><span id="counts">-</span></div>
    <div class="row"><span class="muted">进度</span><span id="progress">-</span></div>
  </div>
  <div class="panel muted" style="line-height:1.6">
    规则：<br/>
    • ball：只标<b>当前发球球</b>；有运动模糊时标整个可见球体/拖影<br/>
    • racket：只标<b>当前发球队员球拍</b>（拍面+可见拍柄）<br/>
    • 不标对手球拍 / 背景球拍 / 桌角 / 球网 / 其它器材<br/>
    • 拖拽框内部=移动；拖拽角点=resize；Del=删除<br/>
    保存后该图即为 <code>HUMAN_VERIFIED</code>，只有它能进训练。
  </div>
  <div id="list"></div>
</div>
<script>
const COLORS = {0: "#ff9d2e", 1: "#2ecc71"};
const NAMES = {0: "ball", 1: "racket"};

let queue = [];
let current = 0;
let boxes = [];          // {class_id, bbox_xyxy:[x1,y1,x2,y2]}
let selected = -1;
let img = new Image();
let zoom = 1, panX = 0, panY = 0;
let dragMode = null, dragStart = null, dragBoxIndex = -1, dragOrig = null;
const HANDLE = 10;

const cv = document.getElementById("cv");
const ctx = cv.getContext("2d");

function api(path, options) {
  return fetch(path, options).then(r => r.json());
}

function fmt(n) { return (Math.round(n * 100) / 100).toString(); }

async function bootstrap() {
  const data = await api("/api/queue");
  queue = data.queue;
  renderList();
  let firstTodo = queue.findIndex(q => !q.verified);
  await load(firstTodo >= 0 ? firstTodo : 0);
}

function renderList() {
  const el = document.getElementById("list");
  el.innerHTML = "";
  queue.forEach((q, i) => {
    const div = document.createElement("div");
    div.className = "item" + (i === current ? " active" : "");
    const left = document.createElement("span");
    left.textContent = (i + 1) + ". " + q.image_id.slice(-28);
    const right = document.createElement("span");
    if (q.verified) { right.className = "badge ok"; right.textContent = "已确认"; }
    else if (q.annotation_source === "MODEL_PROPOSAL") { right.className = "badge todo"; right.textContent = "待确认"; }
    else { right.className = "badge todo"; right.textContent = "无预标"; }
    if (q.has_existing_manual_gt && !q.verified) {
      const ref = document.createElement("span");
      ref.className = "badge ref"; ref.textContent = "有旧标签";
      right.appendChild(document.createTextNode(" "));
      right.appendChild(ref);
    }
    div.appendChild(left); div.appendChild(right);
    div.onclick = () => load(i);
    el.appendChild(div);
  });
}

function load(i) {
  current = Math.max(0, Math.min(queue.length - 1, i));
  const q = queue[current];
  selected = -1;
  boxes = (q.objects || []).map(o => ({
    class_id: o.class_id,
    bbox_xyxy: [o.bbox_xyxy[0], o.bbox_xyxy[1], o.bbox_xyxy[2], o.bbox_xyxy[3]]
  }));
  img = new Image();
  img.onload = () => { fit(); draw(); };
  img.src = "/api/image?id=" + encodeURIComponent(q.image_id) + "&t=" + Date.now();
  document.getElementById("title").textContent = q.image_id;
  document.getElementById("stage").textContent = q.stage_hint;
  document.getElementById("session").textContent = q.session_id;
  document.getElementById("source").textContent = q.source_id;
  document.getElementById("source_kind").textContent = q.annotation_source +
      (q.verified ? "（已确认）" : "");
  updateInfo();
  renderList();
}

function updateInfo() {
  const b = boxes.filter(x => x.class_id === 0).length;
  const r = boxes.filter(x => x.class_id === 1).length;
  document.getElementById("counts").textContent = b + " / " + r;
}

function fit() {
  const wrap = document.getElementById("canvasWrap");
  const sx = wrap.clientWidth / img.width;
  const sy = wrap.clientHeight / img.height;
  zoom = Math.min(sx, sy) * 0.98;
  panX = (wrap.clientWidth - img.width * zoom) / 2;
  panY = (wrap.clientHeight - img.height * zoom) / 2;
  document.getElementById("zoomLabel").textContent = Math.round(zoom * 100) + "%";
}

function toImage(ev) {
  const rect = cv.getBoundingClientRect();
  return { x: (ev.clientX - rect.left - panX) / zoom, y: (ev.clientY - rect.top - panY) / zoom };
}

function draw() {
  const wrap = document.getElementById("canvasWrap");
  cv.width = wrap.clientWidth; cv.height = wrap.clientHeight;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.save();
  ctx.translate(panX, panY); ctx.scale(zoom, zoom);
  if (img.complete && img.width) ctx.drawImage(img, 0, 0);
  boxes.forEach((b, i) => {
    const [x1, y1, x2, y2] = b.bbox_xyxy;
    ctx.lineWidth = (i === selected ? 3.5 : 2) / zoom;
    ctx.strokeStyle = COLORS[b.class_id] || "#fff";
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    const label = NAMES[b.class_id] + " " + fmt(x2 - x1) + "x" + fmt(y2 - y1);
    ctx.font = (14 / zoom) + "px sans-serif";
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = COLORS[b.class_id] || "#fff";
    ctx.fillRect(x1, Math.max(0, y1 - 18 / zoom), tw + 8 / zoom, 18 / zoom);
    ctx.fillStyle = "#111";
    ctx.fillText(label, x1 + 4 / zoom, Math.max(12 / zoom, y1 - 5 / zoom));
    if (i === selected) {
      const s = HANDLE / zoom;
      ctx.fillStyle = "#fff";
      [[x1, y1], [x2, y1], [x1, y2], [x2, y2]].forEach(([hx, hy]) => {
        ctx.fillRect(hx - s / 2, hy - s / 2, s, s);
      });
    }
  });
  ctx.restore();
}

function hitTest(p) {
  for (let i = boxes.length - 1; i >= 0; i--) {
    const [x1, y1, x2, y2] = boxes[i].bbox_xyxy;
    const s = HANDLE / zoom;
    const near = (a, b) => Math.abs(a - b) <= s;
    if (near(p.x, x1) && near(p.y, y1)) return { index: i, mode: "nw" };
    if (near(p.x, x2) && near(p.y, y1)) return { index: i, mode: "ne" };
    if (near(p.x, x1) && near(p.y, y2)) return { index: i, mode: "sw" };
    if (near(p.x, x2) && near(p.y, y2)) return { index: i, mode: "se" };
    if (p.x >= x1 && p.x <= x2 && p.y >= y1 && p.y <= y2) return { index: i, mode: "move" };
  }
  return null;
}

cv.addEventListener("mousedown", ev => {
  const p = toImage(ev);
  const hit = hitTest(p);
  if (hit) {
    selected = hit.index; dragBoxIndex = hit.index; dragMode = hit.mode;
    dragOrig = boxes[hit.index].bbox_xyxy.slice();
  } else {
    dragMode = "create"; dragStart = p; selected = -1;
    dragBoxIndex = boxes.length;
    boxes.push({ class_id: 0, bbox_xyxy: [p.x, p.y, p.x, p.y] });
  }
  dragStart = dragStart || p;
  draw(); updateInfo();
});

cv.addEventListener("mousemove", ev => {
  if (!dragMode) return;
  const p = toImage(ev);
  if (dragMode === "create") {
    boxes[dragBoxIndex].bbox_xyxy = [
      Math.min(dragStart.x, p.x), Math.min(dragStart.y, p.y),
      Math.max(dragStart.x, p.x), Math.max(dragStart.y, p.y)
    ];
  } else if (dragMode === "move") {
    const dx = p.x - dragStart.x, dy = p.y - dragStart.y;
    boxes[dragBoxIndex].bbox_xyxy = [
      dragOrig[0] + dx, dragOrig[1] + dy, dragOrig[2] + dx, dragOrig[3] + dy
    ];
  } else {
    const b = dragOrig.slice();
    if (dragMode.includes("n")) b[1] = p.y;
    if (dragMode.includes("s")) b[3] = p.y;
    if (dragMode.includes("w")) b[0] = p.x;
    if (dragMode.includes("e")) b[2] = p.x;
    boxes[dragBoxIndex].bbox_xyxy = [
      Math.min(b[0], b[2]), Math.min(b[1], b[3]),
      Math.max(b[0], b[2]), Math.max(b[1], b[3])
    ];
  }
  draw(); updateInfo();
});

window.addEventListener("mouseup", () => {
  if (dragMode === "create") {
    const b = boxes[dragBoxIndex].bbox_xyxy;
    if (b[2] - b[0] < 3 || b[3] - b[1] < 3) boxes.splice(dragBoxIndex, 1);
    else selected = dragBoxIndex;
  }
  // clamp 到图像内
  boxes.forEach(bx => {
    bx.bbox_xyxy = [
      Math.max(0, Math.min(img.width, bx.bbox_xyxy[0])),
      Math.max(0, Math.min(img.height, bx.bbox_xyxy[1])),
      Math.max(0, Math.min(img.width, bx.bbox_xyxy[2])),
      Math.max(0, Math.min(img.height, bx.bbox_xyxy[3]))
    ];
  });
  dragMode = null; dragStart = null; dragOrig = null;
  draw(); updateInfo();
});

function addBox(classId) {
  const w = img.width * 0.05, h = img.height * 0.05;
  boxes.push({ class_id: classId, bbox_xyxy: [img.width / 2 - w / 2, img.height / 2 - h / 2, img.width / 2 + w / 2, img.height / 2 + h / 2] });
  selected = boxes.length - 1;
  draw(); updateInfo();
}

async function save(goNext) {
  const q = queue[current];
  const payload = {
    image_id: q.image_id, image_width: img.width, image_height: img.height,
    objects: boxes.map(b => ({ class_id: b.class_id, bbox_xyxy: b.bbox_xyxy }))
  };
  const res = await api("/api/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (res.error) { alert("保存失败：" + res.error); return; }
  queue[current].objects = res.saved.objects;
  queue[current].verified = true;
  queue[current].annotation_source = "HUMAN_VERIFIED";
  document.getElementById("progress").textContent =
      res.progress.human_verified + " / " + res.progress.pool_size + " 已确认";
  document.getElementById("source_kind").textContent = "HUMAN_VERIFIED（已确认）";
  renderList();
  if (goNext) {
    const nextTodo = queue.findIndex((x, i) => i > current && !x.verified);
    const anyTodo = queue.findIndex(x => !x.verified);
    load(nextTodo >= 0 ? nextTodo : (anyTodo >= 0 ? anyTodo : Math.min(queue.length - 1, current + 1)));
  }
}

document.getElementById("prev").onclick = () => load(current - 1);
document.getElementById("next").onclick = () => load(current + 1);
document.getElementById("addBall").onclick = () => addBox(0);
document.getElementById("addRacket").onclick = () => addBox(1);
document.getElementById("delSel").onclick = () => {
  if (selected >= 0) { boxes.splice(selected, 1); selected = -1; draw(); updateInfo(); }
};
document.getElementById("save").onclick = () => save(true);
document.getElementById("reload").onclick = () => load(current);
document.getElementById("fit").onclick = () => { fit(); draw(); };
document.getElementById("zoomIn").onclick = () => { zoom *= 1.25; document.getElementById("zoomLabel").textContent = Math.round(zoom * 100) + "%"; draw(); };
document.getElementById("zoomOut").onclick = () => { zoom /= 1.25; document.getElementById("zoomLabel").textContent = Math.round(zoom * 100) + "%"; draw(); };

window.addEventListener("keydown", ev => {
  if (ev.key === "a" || ev.key === "A") load(current - 1);
  else if (ev.key === "d" || ev.key === "D") load(current + 1);
  else if (ev.key === "1") addBox(0);
  else if (ev.key === "2") addBox(1);
  else if (ev.key === "Delete" || ev.key === "Backspace") {
    if (selected >= 0) { boxes.splice(selected, 1); selected = -1; draw(); updateInfo(); }
  } else if (ev.key === "s" || ev.key === "S" || ev.key === "Enter") save(true);
  else if (ev.key === "f" || ev.key === "F") { fit(); draw(); }
});

window.addEventListener("resize", () => { draw(); });
bootstrap();
</script>
</body>
</html>
"""


@dataclass
class ServerConfig:
    host: str = HOST
    port: int = DEFAULT_PORT


def serve(host: str = HOST, port: int = DEFAULT_PORT) -> None:
    finetune_dir().mkdir(parents=True, exist_ok=True)
    progress = review_progress()
    print("BR FINETUNE annotator")
    print("  pool size      : " + str(progress["pool_size"]))
    print("  human verified : " + str(progress["human_verified"]))
    print("  workspace      : " + str(workspace_dir()))
    print("  annotations    : " + str(annotations_dir()))
    print("  classes        : 0 ball / 1 racket（不含 hand）")
    print("  URL            : http://" + host + ":" + str(port) + "/")
    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BR FINETUNE 标注服务（ball / racket）")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
