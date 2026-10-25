#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unified 3-class ping-pong detector - reference inference.

Classes are FIXED:  0 = ball, 1 = hand, 2 = racket.

Input contract (identical to the C++ DetectorBackend):
  * source frames are GRAY8 (single channel)
  * GRAY8 -> replicate to 3 identical channels -> letterbox to the model square ->
    /255 -> NCHW float32
  * output boxes are mapped back to ORIGINAL image pixels

Usage:
  python infer_unified_3cls.py --source path/to/image.jpg|folder|video.mp4 --out out/
  python infer_unified_3cls.py --source clip.mp4 --conf 0.25 --classes ball,racket
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

NAMES = {0: "ball", 1: "hand", 2: "racket"}
COLOURS = {0: (0, 255, 255), 1: (0, 200, 0), 2: (0, 0, 255)}
HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_ONNX = HERE / "pingpong_yolov8n_gray_3cls_v3_960.onnx"
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}
VID_EXT = {".mp4", ".avi", ".mov", ".mkv"}


def die(msg, code=2):
    sys.stderr.write("ERROR: " + msg + "\n")
    raise SystemExit(code)


def load(onnx_path, threads):
    p = pathlib.Path(onnx_path)
    if not p.is_file():
        die("model not found: %s" % p)
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    sess = ort.InferenceSession(str(p), sess_options=so, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    shape = inp.shape
    if len(shape) != 4 or shape[1] != 3:
        die("unexpected input shape %s (expect [1,3,S,S])" % (shape,))
    return sess, inp.name, int(shape[2])


def preprocess(gray, size):
    h, w = gray.shape[:2]
    s = min(size / w, size / h)
    nw, nh = int(round(w * s)), int(round(h * s))
    rs = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size), 114, np.uint8)
    px, py = (size - nw) // 2, (size - nh) // 2
    canvas[py:py + nh, px:px + nw] = rs
    rgb = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)[:, :, ::-1]
    x = np.ascontiguousarray((rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None])
    return x, s, px, py


def decode(out, s, px, py, w0, h0, conf, iou=0.5, max_det=60):
    scores = out[4:]
    cls = scores.argmax(axis=0)
    sc = scores.max(axis=0)
    idx = np.nonzero(sc >= conf)[0]
    if idx.size == 0:
        return []
    idx = idx[np.argsort(-sc[idx])][:max_det * 10]
    b = out[:4, idx]
    x1 = np.clip((b[0] - b[2] / 2 - px) / s, 0, w0)
    y1 = np.clip((b[1] - b[3] / 2 - py) / s, 0, h0)
    x2 = np.clip((b[0] + b[2] / 2 - px) / s, 0, w0)
    y2 = np.clip((b[1] + b[3] / 2 - py) / s, 0, h0)
    keep = (x2 - x1 >= 1) & (y2 - y1 >= 1)
    dets = [{"xyxy": [float(a), float(c), float(d), float(e)], "score": float(sc[i]),
             "class_id": int(cls[i])}
            for i, a, c, d, e in zip(idx[keep], x1[keep], y1[keep], x2[keep], y2[keep])]
    out2 = []
    for c in sorted({d["class_id"] for d in dets}):
        grp = sorted([d for d in dets if d["class_id"] == c], key=lambda d: -d["score"])
        kept = []
        for d in grp:
            ax1, ay1, ax2, ay2 = d["xyxy"]
            ok = True
            for k in kept:
                bx1, by1, bx2, by2 = k["xyxy"]
                iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
                ih = max(0.0, min(ay2, by2) - max(ay1, by1))
                inter = iw * ih
                if inter > 0:
                    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
                    if inter / ua > iou:
                        ok = False
                        break
            if ok:
                kept.append(d)
            if len(kept) >= max_det:
                break
        out2.extend(kept)
    out2.sort(key=lambda d: -d["score"])
    return out2


def draw(gray, dets):
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for d in dets:
        x1, y1, x2, y2 = [int(round(v)) for v in d["xyxy"]]
        col = COLOURS.get(d["class_id"], (255, 255, 255))
        cv2.rectangle(vis, (x1, y1), (x2, y2), col, 2)
        cv2.putText(vis, "%s %.2f" % (NAMES.get(d["class_id"], "?"), d["score"]),
                    (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    return vis


def read_gray(p):
    buf = np.fromfile(str(p), dtype=np.uint8)
    im = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED) if buf.size else None
    if im is None:
        return None
    return cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=str(DEFAULT_ONNX))
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.50)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--classes", default="", help="comma list, e.g. ball,racket")
    ap.add_argument("--stride", type=int, default=1, help="video frame stride")
    args = ap.parse_args()

    keep_cls = None
    if args.classes.strip():
        keep_cls = {i for i, n in NAMES.items() if n in {s.strip().lower() for s in args.classes.split(",")}}
        if not keep_cls:
            die("no valid class in --classes %r" % args.classes)

    sess, iname, size = load(args.onnx, args.threads)
    src = pathlib.Path(args.source)
    if not src.exists():
        die("source not found: %s" % src)
    outdir = pathlib.Path(args.out)
    (outdir / "vis").mkdir(parents=True, exist_ok=True)
    print("model=%s  input=%dx%d  conf=%.2f  classes=%s"
          % (pathlib.Path(args.onnx).name, size, size, args.conf,
             ",".join(NAMES.values()) if not keep_cls else
             ",".join(NAMES[i] for i in sorted(keep_cls))))

    files = sorted(p for p in src.iterdir() if p.suffix.lower() in IMG_EXT) if src.is_dir() else [src]
    if not files:
        die("no images in %s" % src)

    records, lat, per_cls = [], [], {0: 0, 1: 0, 2: 0}
    for f in files:
        if f.suffix.lower() in VID_EXT:
            cap = cv2.VideoCapture(str(f))
            if not cap.isOpened():
                die("cannot open video %s" % f)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            writer = cv2.VideoWriter(str(outdir / "vis" / (f.stem + "_3cls.mp4")),
                                     cv2.VideoWriter_fourcc(*"mp4v"), fps / max(1, args.stride), (w, h))
            i = -1
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                i += 1
                if args.stride > 1 and i % args.stride:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                x, s, px, py = preprocess(gray, size)
                t0 = time.perf_counter()
                o = sess.run(None, {iname: x})[0][0]
                lat.append((time.perf_counter() - t0) * 1000)
                dets = decode(o, s, px, py, w, h, args.conf, args.iou)
                if keep_cls:
                    dets = [d for d in dets if d["class_id"] in keep_cls]
                for d in dets:
                    per_cls[d["class_id"]] += 1
                writer.write(draw(gray, dets))
                records.append({"frame_index": i, "detections": dets})
            cap.release()
            writer.release()
            (outdir / (f.stem + ".jsonl")).write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
            print("video %s -> %d frames, vis=%s" % (f.name, len(records), (f.stem + "_3cls.mp4")))
        else:
            gray = read_gray(f)
            if gray is None:
                die("cannot read image %s" % f)
            h, w = gray.shape[:2]
            x, s, px, py = preprocess(gray, size)
            t0 = time.perf_counter()
            o = sess.run(None, {iname: x})[0][0]
            lat.append((time.perf_counter() - t0) * 1000)
            dets = decode(o, s, px, py, w, h, args.conf, args.iou)
            if keep_cls:
                dets = [d for d in dets if d["class_id"] in keep_cls]
            for d in dets:
                per_cls[d["class_id"]] += 1
            cv2.imwrite(str(outdir / "vis" / f.name), draw(gray, dets))
            rec = {"image": f.name, "width": w, "height": h,
                   "detections": [dict(d, xyxy_norm=[round(d["xyxy"][0] / w, 6), round(d["xyxy"][1] / h, 6),
                                                     round(d["xyxy"][2] / w, 6), round(d["xyxy"][3] / h, 6)])
                                  for d in dets]}
            records.append(rec)
            (outdir / (f.stem + ".json")).write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
            print("image %-40s ball=%d hand=%d racket=%d" % (
                f.name, sum(1 for d in dets if d["class_id"] == 0),
                sum(1 for d in dets if d["class_id"] == 1),
                sum(1 for d in dets if d["class_id"] == 2)))

    if lat:
        print("SUMMARY frames=%d  mean ONNX run %.1f ms  ball=%d hand=%d racket=%d  out=%s"
              % (len(lat), float(np.mean(lat)), per_cls[0], per_cls[1], per_cls[2], outdir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
