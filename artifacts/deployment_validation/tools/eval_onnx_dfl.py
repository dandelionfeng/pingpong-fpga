#!/usr/bin/env python3
"""FP32 ONNX reference evaluation for the V3 DFL layout (509 fixed val)."""
from __future__ import annotations

import argparse
import json
import pathlib

import cv2
import numpy as np
import onnxruntime as ort

NAMES = {0: "ball", 1: "hand", 2: "racket"}
CONF = {0: 0.20, 1: 0.25, 2: 0.25}
SIZE, PAD = 960, 114


def letterbox(gray):
    h, w = gray.shape[:2]
    s = min(SIZE / w, SIZE / h)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    canvas = np.full((SIZE, SIZE), PAD, np.uint8)
    px, py = (SIZE - nw) // 2, (SIZE - nh) // 2
    canvas[py:py + nh, px:px + nw] = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return np.dstack([canvas, canvas, canvas])[None], s, px, py


def decode(dfl, logits, s, px, py, w0, h0, nms=0.5, max_det=60):
    d = dfl.reshape(4, 16, -1)
    d = d - d.max(axis=1, keepdims=True)
    e = np.exp(d)
    p = e / e.sum(axis=1, keepdims=True)
    dist = (p * np.arange(16, dtype=np.float32).reshape(1, 16, 1)).sum(axis=1)
    strides = np.concatenate([np.full(120 * 120, 8), np.full(60 * 60, 16), np.full(30 * 30, 32)]).astype(np.float32)
    gx = np.concatenate([np.tile(np.arange(120), 120), np.tile(np.arange(60), 60), np.tile(np.arange(30), 30)]).astype(np.float32)
    gy = np.concatenate([np.repeat(np.arange(120), 120), np.repeat(np.arange(60), 60), np.repeat(np.arange(30), 30)]).astype(np.float32)
    ax, ay = (gx + 0.5) * strides, (gy + 0.5) * strides
    x1 = (ax - dist[0] * strides - px) / s
    y1 = (ay - dist[1] * strides - py) / s
    x2 = (ax + dist[2] * strides - px) / s
    y2 = (ay + dist[3] * strides - py) / s
    sc = 1.0 / (1.0 + np.exp(-logits))
    cls = sc.argmax(axis=0)
    smax = sc.max(axis=0)
    dets = []
    for c in (0, 1, 2):
        idx = np.nonzero((cls == c) & (smax >= CONF[c]))[0]
        if idx.size == 0:
            continue
        idx = idx[np.argsort(-smax[idx])][: max_det * 10]
        kept = []
        for i in idx:
            a, b, cc, dd = x1[i], y1[i], x2[i], y2[i]
            if cc - a < 1 or dd - b < 1:
                continue
            cand = [float(np.clip(a, 0, w0)), float(np.clip(b, 0, h0)),
                    float(np.clip(cc, 0, w0)), float(np.clip(dd, 0, h0)), float(smax[i]), c]
            ok = True
            for k in kept:
                iw = max(0.0, min(cand[2], k[2]) - max(cand[0], k[0]))
                ih = max(0.0, min(cand[3], k[3]) - max(cand[1], k[1]))
                inter = iw * ih
                if inter > 0:
                    ua = ((cand[2] - cand[0]) * (cand[3] - cand[1]) + (k[2] - k[0]) * (k[3] - k[1]) - inter)
                    if ua > 0 and inter / ua > nms:
                        ok = False
                        break
            if ok:
                kept.append(cand)
            if len(kept) >= max_det:
                break
        dets.extend(kept)
    return dets


def iou(a, b):
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--limit", type=int, default=509)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    names = [o.name for o in sess.get_outputs()]
    print("outputs", names, flush=True)
    files = sorted(pathlib.Path(args.val).glob("*.jpg"))[: args.limit]
    per = {c: {"tp": 0, "fp": 0, "fn": 0, "gt": 0} for c in NAMES}
    ranges = {"dfl": [1e9, -1e9], "logits": [1e9, -1e9]}
    n = 0
    for p in files:
        g = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        h, w = g.shape[:2]
        lp = pathlib.Path(args.labels) / (p.stem + ".txt")
        gts = []
        for ln in lp.read_text(errors="replace").splitlines() if lp.is_file() else []:
            t = ln.split()
            if len(t) < 5:
                continue
            c = int(float(t[0]))
            cx, cy, bw, bh = (float(v) for v in t[1:5])
            gts.append((c, [(cx - bw / 2) * w, (cy - bh / 2) * h,
                            (cx + bw / 2) * w, (cy + bh / 2) * h]))
        x, s, px, py = letterbox(g)
        outs = sess.run(None, {sess.get_inputs()[0].name: np.transpose(x, (0, 3, 1, 2)).astype(np.float32) / 255.0})
        dfl = logits = None
        for a in outs:
            v = a[0] if a.ndim == 3 else a
            if v.ndim == 2 and v.shape[0] == 64 and dfl is None:
                dfl = v
            elif v.ndim == 2 and v.shape[0] == 3 and logits is None:
                logits = v
        if dfl is None or logits is None:
            print("outputs shapes", [a.shape for a in outs])
            return 2
        ranges["dfl"][0] = min(ranges["dfl"][0], float(dfl.min()))
        ranges["dfl"][1] = max(ranges["dfl"][1], float(dfl.max()))
        ranges["logits"][0] = min(ranges["logits"][0], float(logits.min()))
        ranges["logits"][1] = max(ranges["logits"][1], float(logits.max()))
        dets = decode(dfl, logits, s, px, py, w, h)
        for c in NAMES:
            gl = [b for (cc, b) in gts if cc == c]
            per[c]["gt"] += len(gl)
            used = set()
            for d in [t for t in dets if t[5] == c]:
                best, bi = 0.0, -1
                for k, gg in enumerate(gl):
                    if k in used:
                        continue
                    v = iou(d[:4], gg)
                    if v > best:
                        best, bi = v, k
                if bi >= 0 and best >= 0.5:
                    used.add(bi)
                    per[c]["tp"] += 1
                else:
                    per[c]["fp"] += 1
            per[c]["fn"] += len(gl) - len(used)
        n += 1
        if n % 100 == 0:
            print(f"  {n}/{len(files)}", flush=True)
    rep = {"tag": "fp32_onnx_509", "int8": False, "images": n,
           "value_ranges": {k: [round(v[0], 3), round(v[1], 3)] for k, v in ranges.items()},
           "classes": {}}
    for c, name in NAMES.items():
        d = per[c]
        p_ = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else 0.0
        r_ = d["tp"] / (d["tp"] + d["fn"]) if d["tp"] + d["fn"] else 0.0
        f1 = 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0
        rep["classes"][name] = {"gt": d["gt"], "tp": d["tp"], "fp": d["fp"], "fn": d["fn"],
                                "precision": round(p_, 4), "recall": round(r_, 4), "f1": round(f1, 4)}
        print(f"  {name:7s} GT={d['gt']:4d} TP={d['tp']:4d} FP={d['fp']:4d} FN={d['fn']:4d} "
              f"P={p_:.4f} R={r_:.4f} F1={f1:.4f}")
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
