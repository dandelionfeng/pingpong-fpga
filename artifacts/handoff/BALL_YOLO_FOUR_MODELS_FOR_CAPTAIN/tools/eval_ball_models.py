#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unified inference entry point for the four ball YOLO ONNX models.

Design notes / guarantees
  * The input size is read from each ONNX graph itself (1280 or 960) - the model id never
    hard-codes it, so a 960 graph can never be fed a 1280 tensor.
  * All four models were trained on the same preprocessing (BGR frame -> gray -> three
    identical channels -> letterbox to a square input -> /255 -> NCHW), which is the
    "gray3" convention used everywhere in this project.
  * Output is the raw YOLOv8 head [1, 4+nc, anchors] in *input* pixels, so boxes are
    mapped back through the letterbox into ORIGINAL image pixels before saving.
  * Predictions are written to JSONL (one record per image/frame) with the original file
    name, image size, per-box xyxy in original pixels, normalised xyxy, score and class.
  * Annotated images (and annotated video for video input) are written next to them.

Exit codes: 0 ok, 2 bad arguments / missing files, 3 inference error.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import cv2
import numpy as np
import onnxruntime as ort

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
MODELS = {
    "ball_yolo_v1_1280": "models/ball_yolo_v1_1280.onnx",
    "ball_roboflow_960": "models/ball_roboflow_960.onnx",
    "ball_roboflow_1280": "models/ball_roboflow_1280.onnx",
    "ball_v6_round2": "models/ball_v6_round2.onnx",
}
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
VID_EXT = {".mp4", ".avi", ".mov", ".mkv"}


def die(msg: str, code: int = 3) -> "None":
    sys.stderr.write("ERROR: " + msg + "\n")
    raise SystemExit(code)


def load_model(model_id: str, threads: int):
    if model_id not in MODELS:
        die("unknown model id %r; choose one of %s" % (model_id, ", ".join(MODELS)), 2)
    path = PKG / MODELS[model_id]
    if not path.is_file():
        die("model file not found: %s" % path, 2)
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    sess = ort.InferenceSession(str(path), sess_options=so,
                                providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    shape = inp.shape
    if len(shape) != 4 or not all(isinstance(v, int) for v in shape):
        die("model %s has an unexpected input shape %s (expected [1,3,S,S])"
            % (model_id, shape), 3)
    _, c, h, w = shape
    if c != 3:
        die("model %s expects %d channels, the loader only supports 3 (gray3)"
            % (model_id, c), 3)
    if h != w:
        die("model %s expects a non-square input %dx%d" % (model_id, h, w), 3)
    return sess, inp.name, int(h)


def letterbox_gray3(bgr, size):
    """BGR frame -> gray -> 3 channels -> letterbox to (size,size). Returns tensor + meta."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    h0, w0 = gray.shape[:2]
    s = min(size / w0, size / h0)
    nw, nh = int(round(w0 * s)), int(round(h0 * s))
    resized = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size), 114, np.uint8)
    pad_x, pad_y = (size - nw) // 2, (size - nh) // 2
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)[:, :, ::-1]
    tensor = np.ascontiguousarray(
        (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None])
    return tensor, {"scale": s, "pad_x": pad_x, "pad_y": pad_y, "w0": w0, "h0": h0}


def decode(out, meta, size, conf_floor, iou_thr, max_det):
    """out: (4+nc, anchors) raw head -> list of dicts in ORIGINAL image pixels."""
    out = np.asarray(out)
    if out.ndim != 2:
        die("unexpected model output rank %d" % out.ndim, 3)
    nc = out.shape[0] - 4
    scores_all = out[4:]
    cls_ids = scores_all.argmax(axis=0)
    scores = scores_all.max(axis=0)
    idx = np.nonzero(scores >= conf_floor)[0]
    if idx.size == 0:
        return [], nc
    idx = idx[np.argsort(-scores[idx])][:max_det * 10]
    s = meta["scale"]
    px, py = meta["pad_x"], meta["pad_y"]
    boxes = out[:4, idx].astype(np.float32)
    x1 = np.clip((boxes[0] - boxes[2] / 2 - px) / s, 0, meta["w0"])
    y1 = np.clip((boxes[1] - boxes[3] / 2 - py) / s, 0, meta["h0"])
    x2 = np.clip((boxes[0] + boxes[2] / 2 - px) / s, 0, meta["w0"])
    y2 = np.clip((boxes[1] + boxes[3] / 2 - py) / s, 0, meta["h0"])
    keep = (x2 - x1 >= 1) & (y2 - y1 >= 1)
    dets = []
    for i, a, b, c, d in zip(idx[keep], x1[keep], y1[keep], x2[keep], y2[keep]):
        dets.append({"xyxy": [float(a), float(b), float(c), float(d)],
                     "score": float(scores[i]), "class_id": int(cls_ids[i])})
    # class-aware NMS
    final = []
    for cid in sorted({d["class_id"] for d in dets}):
        group = [d for d in dets if d["class_id"] == cid]
        keep_idx = cv2.dnn.NMSBoxes(
            [[d["xyxy"][0], d["xyxy"][1], d["xyxy"][2] - d["xyxy"][0],
              d["xyxy"][3] - d["xyxy"][1]] for d in group],
            [d["score"] for d in group], float(conf_floor), float(iou_thr))
        for j in np.array(keep_idx).flatten():
            final.append(group[int(j)])
    final.sort(key=lambda d: -d["score"])
    return final[:max_det], nc


def draw(img, dets, names):
    out = img.copy()
    for d in dets:
        x1, y1, x2, y2 = [int(round(v)) for v in d["xyxy"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = "%s %.2f" % (names.get(d["class_id"], str(d["class_id"])), d["score"])
        cv2.putText(out, label, (x1, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 0), 1, cv2.LINE_AA)
    return out


def run_image(sess, iname, size, path, conf, iou, max_det, out_dir, names):
    buf = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None
    if img is None:
        die("cannot read image: %s" % path, 3)
    tensor, meta = letterbox_gray3(img, size)
    t0 = time.perf_counter()
    out = sess.run(None, {iname: tensor})[0][0]
    dt = (time.perf_counter() - t0) * 1000.0
    dets, nc = decode(out, meta, size, conf, iou, max_det)
    h0, w0 = meta["h0"], meta["w0"]
    rec = {"image": path.name, "width": w0, "height": h0,
           "inference_ms": round(dt, 2), "num_classes": nc,
           "detections": [dict(d, xyxy_norm=[round(d["xyxy"][0] / w0, 6),
                                             round(d["xyxy"][1] / h0, 6),
                                             round(d["xyxy"][2] / w0, 6),
                                             round(d["xyxy"][3] / h0, 6)]) for d in dets]}
    vis_path = out_dir / "vis" / path.name
    vis_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(vis_path), draw(img, dets, names))
    return rec


def run_video(sess, iname, size, path, conf, iou, max_det, out_dir, names, stride):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        die("cannot open video: %s" % path, 3)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = None
    vis_dir = out_dir / "vis"
    vis_dir.mkdir(parents=True, exist_ok=True)
    vis_path = vis_dir / (path.stem + "_annotated.mp4")
    recs = []
    idx = -1
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        idx += 1
        if stride > 1 and idx % stride:
            continue
        tensor, meta = letterbox_gray3(frame, size)
        t0 = time.perf_counter()
        out = sess.run(None, {iname: tensor})[0][0]
        dt = (time.perf_counter() - t0) * 1000.0
        dets, nc = decode(out, meta, size, conf, iou, max_det)
        vis = draw(frame, dets, names)
        if writer is None:
            writer = cv2.VideoWriter(str(vis_path), cv2.VideoWriter_fourcc(*"mp4v"),
                                     fps / max(1, stride), (w, h))
            if not writer.isOpened():
                die("cannot create output video: %s" % vis_path, 3)
        writer.write(vis)
        recs.append({"frame_index": idx, "width": meta["w0"], "height": meta["h0"],
                     "inference_ms": round(dt, 2), "num_classes": nc,
                     "detections": dets})
    cap.release()
    if writer is not None:
        writer.release()
    if not recs:
        die("no frames decoded from %s" % path, 3)
    return recs, vis_path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run one of the four ball YOLO ONNX models on an image, a folder or a video.")
    ap.add_argument("--model", required=True, choices=sorted(MODELS),
                    help="model id (see README_CAPTAIN.md)")
    ap.add_argument("--source", required=True,
                    help="image file, image folder, or video file")
    ap.add_argument("--out", default=None,
                    help="output folder (default: ./output/<model>)")
    ap.add_argument("--conf", type=float, default=0.10,
                    help="score threshold for saved detections (default 0.10)")
    ap.add_argument("--iou", type=float, default=0.50, help="NMS IoU (default 0.50)")
    ap.add_argument("--max-det", type=int, default=30, help="max boxes per frame")
    ap.add_argument("--stride", type=int, default=1, help="process every Nth video frame")
    ap.add_argument("--threads", type=int, default=0, help="ORT intra-op threads (0=auto)")
    args = ap.parse_args()

    sess, iname, size = load_model(args.model, args.threads)
    src = pathlib.Path(args.source)
    if not src.exists():
        die("source not found: %s" % src, 2)
    out_dir = pathlib.Path(args.out) if args.out else (pathlib.Path.cwd() / "output" / args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    # single-class models in this package: class 0 = ball
    names = {0: "ball"}

    files = []
    if src.is_dir():
        files = sorted(p for p in src.iterdir() if p.suffix.lower() in IMG_EXT)
        if not files:
            die("no images found in %s" % src, 2)
    else:
        files = [src]

    print("model=%s  file=%s  input=%dx%d  conf=%.2f  iou=%.2f"
          % (args.model, MODELS[args.model], size, size, args.conf, args.iou))
    total_frames = 0
    frames_with_det = 0
    lat = []
    for f in files:
        ext = f.suffix.lower()
        if ext in VID_EXT:
            recs, vis = run_video(sess, iname, size, f, args.conf, args.iou,
                                  args.max_det, out_dir, names, max(1, args.stride))
            jname = out_dir / (f.stem + ".jsonl")
            with open(jname, "w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            total_frames += len(recs)
            frames_with_det += sum(1 for r in recs if r["detections"])
            lat += [r["inference_ms"] for r in recs]
            print("  video %s -> %d frames, %d with detections, vis=%s"
                  % (f.name, len(recs), sum(1 for r in recs if r["detections"]), vis.name))
        elif ext in IMG_EXT:
            rec = run_image(sess, iname, size, f, args.conf, args.iou, args.max_det,
                            out_dir, names)
            jname = out_dir / "predictions.jsonl"
            with open(jname, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total_frames += 1
            frames_with_det += 1 if rec["detections"] else 0
            lat.append(rec["inference_ms"])
            print("  image %-40s det=%d  top=%.3f  %.1f ms"
                  % (f.name, len(rec["detections"]),
                     rec["detections"][0]["score"] if rec["detections"] else 0.0,
                     rec["inference_ms"]))
        else:
            die("unsupported source type: %s" % f, 2)

    print("SUMMARY model=%s frames=%d frames_with_detections=%d mean_ms=%.1f out=%s"
          % (args.model, total_frames, frames_with_det,
             float(np.mean(lat)) if lat else 0.0, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
