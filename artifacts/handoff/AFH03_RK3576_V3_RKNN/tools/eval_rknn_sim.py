#!/usr/bin/env python3
"""RKNN simulator accuracy check for the V3 3-class model, identical metrics to the PC pipeline.

Runs on a Linux box with rknn-toolkit2 (simulator target). It is NOT a board measurement:
the simulator models the NPU's numeric behaviour, not its speed.

Usage:
  python3 eval_rknn_sim.py --rknn out/v3_six_int8.rknn --val val_imgs --labels val_labels --tag int8
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

import cv2
import numpy as np

NAMES = {0: "ball", 1: "hand", 2: "racket"}
CONF = {0: 0.20, 1: 0.25, 2: 0.25}
PAD = 114
SIZE = 960


def letterbox(gray):
    h, w = gray.shape[:2]
    s = min(SIZE / w, SIZE / h)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    canvas = np.full((SIZE, SIZE), PAD, np.uint8)
    px, py = (SIZE - nw) // 2, (SIZE - nh) // 2
    canvas[py:py + nh, px:px + nw] = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_LINEAR)
    rgb = np.dstack([canvas, canvas, canvas])
    return rgb[None], s, px, py


def decode(out, s, px, py, w0, h0, conf, iou=0.5, max_det=60):
    """out: [7, N] -> detections in original image pixels."""
    scores = out[4:]
    cls = scores.argmax(axis=0)
    sc = scores.max(axis=0)
    dets = []
    for c in (0, 1, 2):
        idx = np.nonzero((cls == c) & (sc >= conf[c]))[0]
        if idx.size == 0:
            continue
        idx = idx[np.argsort(-sc[idx])][:max_det * 10]
        b = out[:4, idx]
        x1 = np.clip((b[0] - b[2] / 2 - px) / s, 0, w0)
        y1 = np.clip((b[1] - b[3] / 2 - py) / s, 0, h0)
        x2 = np.clip((b[0] + b[2] / 2 - px) / s, 0, w0)
        y2 = np.clip((b[1] + b[3] / 2 - py) / s, 0, h0)
        kept = []
        for a, bb, cc, dd, sc_ in zip(x1, y1, x2, y2, sc[idx]):
            if cc - a < 1 or dd - bb < 1:
                continue
            cand = [float(a), float(bb), float(cc), float(dd)]
            dup = False
            for k in kept:
                iw = max(0.0, min(cand[2], k[2]) - max(cand[0], k[0]))
                ih = max(0.0, min(cand[3], k[3]) - max(cand[1], k[1]))
                inter = iw * ih
                if inter > 0:
                    ua = ((cand[2] - cand[0]) * (cand[3] - cand[1]) + (k[2] - k[0]) * (k[3] - k[1]) - inter)
                    if ua > 0 and inter / ua > iou:
                        dup = True
                        break
            if not dup:
                kept.append(cand + [float(sc_), c])
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


def ap_from_pairs(pairs, n_gt):
    if n_gt == 0:
        return 0.0
    pairs = sorted(pairs, key=lambda t: -t[0])
    tp = fp = 0
    rec, prec = [0.0], [1.0]
    for score, is_tp in pairs:
        tp += 1 if is_tp else 0
        fp += 0 if is_tp else 1
        rec.append(tp / n_gt)
        prec.append(tp / (tp + fp))
    for i in range(len(prec) - 2, -1, -1):
        prec[i] = max(prec[i], prec[i + 1])
    ap = 0.0
    for i in range(1, len(rec)):
        if rec[i] != rec[i - 1]:
            ap += (rec[i] - rec[i - 1]) * prec[i]
    return ap


def load_gt(lp, w, h):
    gts = []
    if not lp.is_file():
        return gts
    for ln in lp.read_text(errors="replace").splitlines():
        t = ln.split()
        if len(t) < 5:
            continue
        c = int(float(t[0]))
        cx, cy, bw, bh = (float(v) for v in t[1:5])
        gts.append((c, [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h]))
    return gts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rknn", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--tag", default="model")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from rknn.api import RKNN
    r = RKNN(verbose=False)
    assert r.load_rknn(args.rknn) == 0, "load_rknn failed"
    assert r.init_runtime() == 0, "init_runtime failed"
    print("model %s loaded (simulator)" % args.rknn, flush=True)

    files = sorted(pathlib.Path(args.val).glob("*.jpg"))
    if args.limit:
        files = files[: args.limit]
    per = {c: {"tp": 0, "fp": 0, "fn": 0, "pairs": [], "gt": 0} for c in NAMES}
    n_ok = 0
    for p in files:
        g = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        h, w = g.shape[:2]
        gts = load_gt(pathlib.Path(args.labels) / (p.stem + ".txt"), w, h)
        x, s, px, py = letterbox(g)
        outs = r.inference(inputs=[x])
        target = None
        for o in outs:
            a = np.array(o)
            if a.ndim == 3 and a.shape[1] == 7:
                target = a[0]
                break
        if target is None:
            for o in outs:
                a = np.array(o).squeeze()
                if a.ndim == 2 and a.shape[0] == 7:
                    target = a
                    break
        if target is None:
            print("could not find [7,N] output; shapes:", [np.array(o).shape for o in outs])
            return 2
        dets = decode(target, s, px, py, w, h, CONF)
        for c in NAMES:
            gl = [b for (cc, b) in gts if cc == c]
            per[c]["gt"] += len(gl)
            used = set()
            for d in [x_ for x_ in dets if x_[5] == c]:
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
                    per[c]["pairs"].append((d[4], True))
                else:
                    per[c]["fp"] += 1
                    per[c]["pairs"].append((d[4], False))
            per[c]["fn"] += len(gl) - len(used)
        n_ok += 1
        if n_ok % 100 == 0:
            print("  %d/%d" % (n_ok, len(files)), flush=True)

    rep = {"tag": args.tag, "rknn": args.rknn, "images": n_ok, "conf": CONF, "classes": {}}
    print("=== %s (%d images) ===" % (args.tag, n_ok))
    for c, name in NAMES.items():
        d = per[c]
        p = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else 0.0
        rc = d["tp"] / (d["tp"] + d["fn"]) if d["tp"] + d["fn"] else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        a50 = ap_from_pairs(d["pairs"], d["gt"])
        rep["classes"][name] = {"gt": d["gt"], "tp": d["tp"], "fp": d["fp"], "fn": d["fn"],
                                "precision": round(p, 4), "recall": round(rc, 4),
                                "f1": round(f1, 4), "ap50": round(a50, 4)}
        print("  %-7s GT=%4d TP=%4d FP=%4d FN=%4d | P=%.4f R=%.4f F1=%.4f AP50=%.4f"
              % (name, d["gt"], d["tp"], d["fp"], d["fn"], p, rc, f1, a50))
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print("report:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
