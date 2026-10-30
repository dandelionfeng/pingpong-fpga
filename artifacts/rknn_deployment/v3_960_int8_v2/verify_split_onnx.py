#!/usr/bin/env python3
"""Verify the split-output ONNX against the original V3 on the same 509 val images.

Checks three levels:
  1. numeric: cat(boxes, scores) from the split model must equal the original output0
  2. decode  : decoding the split outputs must give the same boxes/scores as decoding output0
  3. metrics : per-class P/R/F1/AP50 on the fixed val, identical to the V3 baseline

Also validates the "dfl" layout by running the DFL decode in numpy and comparing with the
box branch - this is the same math the C++ decoder must implement.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tmp"))
import eval_racket as ER  # noqa: E402
import eval_unified_3cls as EU  # noqa: E402

CONF = {0: 0.20, 1: 0.25, 2: 0.25}
SIZE = 960


def letterbox(gray):
    return ER.letterbox_gray3(gray, SIZE)


def nms_decode(out, s, px, py, w0, h0):
    """out: [7, N] -> decoded detections (original-image pixels)."""
    return EU.decode_all(out, s, px, py, w0, h0)


def dfl_decode(dfl, logits, s, px, py, w0, h0):
    """Rockchip-style: dfl [64,N] logits -> distances -> xyxy; logits [3,N] -> sigmoid scores."""
    n = dfl.shape[1]
    # 4 sides x 16 bins, laid out side-major
    d = dfl.reshape(4, 16, n)
    d = d - d.max(axis=1, keepdims=True)
    e = np.exp(d)
    prob = e / e.sum(axis=1, keepdims=True)
    bins = np.arange(16, dtype=np.float32).reshape(1, 16, 1)
    dist = (prob * bins).sum(axis=1)          # [4, N]
    # anchors: P3 120x120, P4 60x60, P5 30x30 (stride 8/16/32), centre offset 0.5
    stride = np.concatenate([np.full(120 * 120, 8), np.full(60 * 60, 16), np.full(30 * 30, 32)]).astype(np.float32)
    gx = np.concatenate([np.tile(np.arange(120), 120), np.tile(np.arange(60), 60), np.tile(np.arange(30), 30)]).astype(np.float32)
    gy = np.concatenate([np.repeat(np.arange(120), 120), np.repeat(np.arange(60), 60), np.repeat(np.arange(30), 30)]).astype(np.float32)
    ax = (gx + 0.5) * stride
    ay = (gy + 0.5) * stride
    x1 = ax - dist[0] * stride
    y1 = ay - dist[1] * stride
    x2 = ax + dist[2] * stride
    y2 = ay + dist[3] * stride
    sc = 1.0 / (1.0 + np.exp(-logits))
    cls = sc.argmax(axis=0)
    smax = sc.max(axis=0)
    dets = []
    for c in (0, 1, 2):
        idx = np.nonzero((cls == c) & (smax >= CONF[c]))[0]
        if idx.size == 0:
            continue
        idx = idx[np.argsort(-smax[idx])][:600]
        cand = []
        for i in idx:
            a = (x1[i] - px) / s
            b = (y1[i] - py) / s
            cc = (x2[i] - px) / s
            dd = (y2[i] - py) / s
            if cc - a < 1 or dd - b < 1:
                continue
            cand.append([float(max(0, a)), float(max(0, b)), float(min(w0, cc)), float(min(h0, dd)), float(smax[i]), c])
        kept = []
        for d_ in cand:
            if all(ER.iou(d_[:4], k[:4]) <= 0.5 for k in kept):
                kept.append(d_)
            if len(kept) >= 60:
                break
        dets.extend(kept)
    return [{"xyxy": d_[:4], "score": d_[4], "cls": d_[5]} for d_ in dets]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--dfl", default="")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    s_orig = ort.InferenceSession(args.orig, sess_options=so, providers=["CPUExecutionProvider"])
    s_split = ort.InferenceSession(args.split, sess_options=so, providers=["CPUExecutionProvider"])
    s_dfl = ort.InferenceSession(args.dfl, sess_options=so, providers=["CPUExecutionProvider"]) if args.dfl else None
    print("split outputs:", [(o.name, o.shape) for o in s_split.get_outputs()])
    if s_dfl:
        print("dfl outputs:", [(o.name, o.shape) for o in s_dfl.get_outputs()])

    items = EU.load_gt(pathlib.Path(args.dataset), "val")
    if args.n:
        items = items[: args.n]

    maxdiff, bad = 0.0, 0
    det_orig, det_split, det_dfl = [], [], []
    for k, it in enumerate(items):
        x, s, px, py = letterbox(it["gray"])
        w0, h0 = it["gray"].shape[1], it["gray"].shape[0]
        o0 = s_orig.run(None, {"images": x})[0][0]
        boxes, scores = s_split.run(None, {"images": x})
        merged = np.concatenate([boxes[0], scores[0]], axis=0)
        maxdiff = max(maxdiff, float(np.abs(o0 - merged).max()))
        if np.abs(o0 - merged).max() > 1e-3:
            bad += 1
        det_orig.append(nms_decode(o0, s, px, py, w0, h0))
        det_split.append(nms_decode(merged, s, px, py, w0, h0))
        if s_dfl:
            dfl, logits = s_dfl.run(None, {"images": x})
            det_dfl.append(dfl_decode(dfl[0], logits[0], s, px, py, w0, h0))
        if (k + 1) % 100 == 0:
            print("  %d/%d" % (k + 1, len(items)), flush=True)

    print("max |cat(split) - output0| = %.2e  (frames over 1e-3: %d)" % (maxdiff, bad))

    def metrics(dets):
        rep = {}
        for cid, name in ((0, "ball"), (1, "hand"), (2, "racket")):
            n_gt = sum(1 for it in items for (c, _) in it["gts"] if c == cid)
            TP = FP = FN = 0
            pairs = []
            for d, it in zip(dets, items):
                gts = [b for (c, b) in it["gts"] if c == cid]
                keep = [d_ for d_ in d if d_["cls"] == cid and d_["score"] >= CONF[cid]]
                used = set()
                for det in keep:
                    best, bi = 0.0, -1
                    for i, g in enumerate(gts):
                        if i in used:
                            continue
                        v = ER.iou(det["xyxy"], g)
                        if v > best:
                            best, bi = v, i
                    if bi >= 0 and best >= 0.5:
                        used.add(bi)
                        TP += 1
                        pairs.append((det["score"], True))
                    else:
                        FP += 1
                        pairs.append((det["score"], False))
                FN += len(gts) - len(used)
            p = TP / (TP + FP) if TP + FP else 0.0
            r = TP / (TP + FN) if TP + FN else 0.0
            rep[name] = {"gt": n_gt, "tp": TP, "fp": FP, "fn": FN, "precision": round(p, 4),
                         "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
                         "ap50": round(ER.ap_from_pairs(pairs, n_gt), 4)}
        return rep

    out = {"images": len(items), "max_abs_diff": maxdiff, "frames_over_1e-3": bad,
           "orig": metrics(det_orig), "split": metrics(det_split)}
    if s_dfl:
        out["dfl"] = metrics(det_dfl)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
