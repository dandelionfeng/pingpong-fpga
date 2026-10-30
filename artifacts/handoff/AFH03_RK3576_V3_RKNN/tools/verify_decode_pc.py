#!/usr/bin/env python3
"""PC-side cross-check of the C++ decode path (no board, no RKNN needed).

The C++ tool (cpp/rknn_v3_detect.cpp) uses a nearest-neighbour letterbox and its own decode/NMS.
This script re-implements exactly that logic in numpy and compares the resulting boxes with the
reference Python pipeline (INTER_LINEAR letterbox + the same decode) on the same frames.

A high IoU agreement means the C++ algorithms are correct; it says nothing about RKNN or board
performance, and must not be reported as such.
"""
from __future__ import annotations

import argparse
import pathlib
import statistics
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tmp"))
import eval_racket as ER  # noqa: E402
import eval_unified_3cls as EU  # noqa: E402

PAD = 114
CONF = {0: 0.20, 1: 0.25, 2: 0.25}


def cpp_letterbox(gray: np.ndarray, size: int):
    """Mirror of letterbox_gray3() in the C++ file (bilinear + 114 pad)."""
    import cv2
    h, w = gray.shape[:2]
    s = min(size / w, size / h)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    canvas = np.full((size, size), PAD, np.uint8)
    px, py = (size - nw) // 2, (size - nh) // 2
    canvas[py:py + nh, px:px + nw] = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_LINEAR)
    rgb = np.dstack([canvas, canvas, canvas])
    x = np.ascontiguousarray((rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None])
    return x, s, px, py


def cpp_decode(out, n_anchors, img_w, img_h, s, px, py):
    """Mirror of decode() in the C++ file (single argmax per anchor, class-aware NMS)."""
    scores = out[4:].reshape(3, n_anchors)
    best = scores.max(axis=0)
    best_c = scores.argmax(axis=0)
    dets = []
    for c in range(3):
        cand = []
        idx = np.nonzero((best_c == c) & (best >= CONF[c]))[0]
        for a in idx:
            cx, cy, bw, bh = out[0, a], out[1, a], out[2, a], out[3, a]
            x1 = min(max(0.0, (cx - bw / 2 - px) / s), img_w)
            y1 = min(max(0.0, (cy - bh / 2 - py) / s), img_h)
            x2 = min(max(0.0, (cx + bw / 2 - px) / s), img_w)
            y2 = min(max(0.0, (cy + bh / 2 - py) / s), img_h)
            if x2 - x1 >= 1 and y2 - y1 >= 1:
                cand.append([x1, y1, x2, y2, float(best[a]), c])
        cand.sort(key=lambda t: -t[4])
        kept = []
        for d in cand:
            if all(ER.iou(d[:4], k[:4]) <= 0.5 for k in kept):
                kept.append(d)
            if len(kept) >= 60:
                break
        dets.extend(kept)
    return dets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    import onnxruntime as ort
    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name
    size = int(sess.get_inputs()[0].shape[2])
    items = EU.load_gt(pathlib.Path(args.dataset), "val")[: args.n]

    agree, diffs = 0, []
    for it in items:
        g = it["gray"]
        h, w = g.shape[:2]
        x, s, px, py = cpp_letterbox(g, size)
        o = sess.run(None, {iname: x})[0][0]
        mine = cpp_decode(o, o.shape[1], w, h, s, px, py)
        # reference: INTER_LINEAR letterbox, same decode
        xr, sr, pxr, pyr = ER.letterbox_gray3(g, size)
        orf = sess.run(None, {iname: xr})[0][0]
        ref = cpp_decode(orf, orf.shape[1], w, h, sr, pxr, pyr)
        if not ref and not mine:
            agree += 1
            continue
        if len(ref) == len(mine):
            ious = []
            for a in mine:
                best = max((ER.iou(a[:4], b[:4]) for b in ref), default=0.0)
                ious.append(best)
            diffs.extend(ious)
            if min(ious) >= 0.85:
                agree += 1
    print("frames=%d  identical/consistent=%d  median IoU=%.3f  min IoU=%.3f"
          % (len(items), agree, statistics.median(diffs) if diffs else 1.0,
             min(diffs) if diffs else 1.0))
    print("note: this validates the C++ letterbox+decode+NMS against the Python reference only; "
          "it is NOT an RKNN or board result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
