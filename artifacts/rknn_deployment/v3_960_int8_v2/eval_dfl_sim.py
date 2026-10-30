#!/usr/bin/env python3
"""INT8 accuracy via the DFL layout (model-zoo style), measured on the RKNN simulator.

The 6-output V3 ONNX already exposes the DFL logits ([1,64,18900]) and the PRE-sigmoid class
logits ([1,3,18900]) as separate tensors. They are NOT shared with the concat tensor, so RKNN
gives them their own quantisation scales - unlike `scores`, which is one of the concat inputs and
inherits its coarse, box-dominated scale.

Decode: softmax over the 16 DFL bins -> expectation -> distances -> xyxy, then sigmoid on the
class logits. Identical maths to the C++ decoder.

Usage (Linux, rknn-toolkit2):
  python3 eval_dfl_sim.py --onnx pingpong_yolov8n_gray_3cls_v3_960_960.onnx \
      --calib calib_list_linux.txt --val val_imgs --labels val_labels --limit 300 --int8
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

CONF = {0: 0.20, 1: 0.25, 2: 0.25}
NAMES = {0: "ball", 1: "hand", 2: "racket"}
SIZE, PAD = 960, 114


def letterbox(gray):
    h, w = gray.shape[:2]
    s = min(SIZE / w, SIZE / h)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    canvas = np.full((SIZE, SIZE), PAD, np.uint8)
    px, py = (SIZE - nw) // 2, (SIZE - nh) // 2
    canvas[py:py + nh, px:px + nw] = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return np.dstack([canvas, canvas, canvas])[None], s, px, py


def dfl_decode(dfl, logits, s, px, py, w0, h0, conf=CONF, nms=0.5, max_det=60):
    n = dfl.shape[1]
    d = dfl.reshape(4, 16, n)
    d = d - d.max(axis=1, keepdims=True)
    e = np.exp(d)
    prob = e / e.sum(axis=1, keepdims=True)
    bins = np.arange(16, dtype=np.float32).reshape(1, 16, 1)
    dist = (prob * bins).sum(axis=1)
    strides = np.concatenate([np.full(120 * 120, 8), np.full(60 * 60, 16),
                              np.full(30 * 30, 32)]).astype(np.float32)
    gx = np.concatenate([np.tile(np.arange(120), 120), np.tile(np.arange(60), 60),
                         np.tile(np.arange(30), 30)]).astype(np.float32)
    gy = np.concatenate([np.repeat(np.arange(120), 120), np.repeat(np.arange(60), 60),
                         np.repeat(np.arange(30), 30)]).astype(np.float32)
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
        idx = np.nonzero((cls == c) & (smax >= conf[c]))[0]
        if idx.size == 0:
            continue
        idx = idx[np.argsort(-smax[idx])][: max_det * 10]
        cand = []
        for i in idx:
            a, b, cc, dd = x1[i], y1[i], x2[i], y2[i]
            if cc - a < 1 or dd - b < 1:
                continue
            cand.append([float(np.clip(a, 0, w0)), float(np.clip(b, 0, h0)),
                         float(np.clip(cc, 0, w0)), float(np.clip(dd, 0, h0)),
                         float(smax[i]), c])
        kept = []
        for d_ in cand:
            ok = True
            for k in kept:
                iw = max(0.0, min(d_[2], k[2]) - max(d_[0], k[0]))
                ih = max(0.0, min(d_[3], k[3]) - max(d_[1], k[1]))
                inter = iw * ih
                if inter > 0:
                    ua = ((d_[2] - d_[0]) * (d_[3] - d_[1]) + (k[2] - k[0]) * (k[3] - k[1]) - inter)
                    if ua > 0 and inter / ua > nms:
                        ok = False
                        break
            if ok:
                kept.append(d_)
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


def ap50(pairs, n_gt):
    if n_gt == 0:
        return 0.0
    pairs = sorted(pairs, key=lambda t: -t[0])
    tp = fp = 0
    rec, prec = [0.0], [1.0]
    for _, is_tp in pairs:
        tp += int(is_tp)
        fp += int(not is_tp)
        rec.append(tp / n_gt)
        prec.append(tp / (tp + fp))
    for i in range(len(prec) - 2, -1, -1):
        prec[i] = max(prec[i], prec[i + 1])
    return sum((rec[i] - rec[i - 1]) * prec[i] for i in range(1, len(rec)) if rec[i] != rec[i - 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--calib", default=None)
    ap.add_argument("--val", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--platform", default="rk3588")
    ap.add_argument("--tag", default="dfl")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from rknn.api import RKNN
    r = RKNN(verbose=False)
    r.config(target_platform=args.platform, mean_values=[[0, 0, 0]],
             std_values=[[255, 255, 255]], optimization_level=3)
    assert r.load_onnx(model=args.onnx) == 0
    ret = r.build(do_quantization=args.int8, dataset=args.calib if args.int8 else None)
    print("build ret =", ret, flush=True)
    if ret != 0:
        return 1
    assert r.init_runtime() == 0

    files = sorted(pathlib.Path(args.val).glob("*.jpg"))
    if args.limit:
        files = files[: args.limit]
    per = {c: {"tp": 0, "fp": 0, "fn": 0, "gt": 0, "pairs": []} for c in NAMES}
    ranges = {"dfl": [1e9, -1e9], "logits": [1e9, -1e9]}
    n = 0
    for p in files:
        g = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        h, w = g.shape[:2]
        lp = pathlib.Path(args.labels) / (p.stem + ".txt")
        gts = []
        if lp.is_file():
            for ln in lp.read_text(errors="replace").splitlines():
                t = ln.split()
                if len(t) < 5:
                    continue
                c = int(float(t[0]))
                cx, cy, bw, bh = (float(v) for v in t[1:5])
                gts.append((c, [(cx - bw / 2) * w, (cy - bh / 2) * h,
                                (cx + bw / 2) * w, (cy + bh / 2) * h]))
        x, s, px, py = letterbox(g)
        outs = [np.array(o) for o in r.inference(inputs=[x])]
        dfl = logits = None
        for a in outs:
            v = a[0] if a.ndim == 3 else a
            if v.ndim == 2 and v.shape[0] == 64 and dfl is None:
                dfl = v
            elif v.ndim == 2 and v.shape[0] == 3 and logits is None:
                logits = v
        if dfl is None or logits is None:
            print("outputs:", [a.shape for a in outs])
            return 2
        ranges["dfl"][0] = min(ranges["dfl"][0], float(dfl.min()))
        ranges["dfl"][1] = max(ranges["dfl"][1], float(dfl.max()))
        ranges["logits"][0] = min(ranges["logits"][0], float(logits.min()))
        ranges["logits"][1] = max(ranges["logits"][1], float(logits.max()))
        dets = dfl_decode(dfl, logits, s, px, py, w, h)
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
                    per[c]["pairs"].append((d[4], True))
                else:
                    per[c]["fp"] += 1
                    per[c]["pairs"].append((d[4], False))
            per[c]["fn"] += len(gl) - len(used)
        n += 1
        if n % 100 == 0:
            print("  %d/%d" % (n, len(files)), flush=True)

    rep = {"tag": args.tag, "int8": args.int8, "images": n,
           "value_ranges": {k: [round(v[0], 3), round(v[1], 3)] for k, v in ranges.items()},
           "classes": {}}
    print("=== %s | int8=%s | %d images | dfl range %s | logits range %s ==="
          % (args.tag, args.int8, n, rep["value_ranges"]["dfl"], rep["value_ranges"]["logits"]))
    for c, name in NAMES.items():
        d = per[c]
        p_ = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else 0.0
        r_ = d["tp"] / (d["tp"] + d["fn"]) if d["tp"] + d["fn"] else 0.0
        f1 = 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0
        a = ap50(d["pairs"], d["gt"])
        rep["classes"][name] = {"gt": d["gt"], "tp": d["tp"], "fp": d["fp"], "fn": d["fn"],
                                "precision": round(p_, 4), "recall": round(r_, 4),
                                "f1": round(f1, 4), "ap50": round(a, 4)}
        print("  %-7s GT=%4d TP=%4d FP=%4d FN=%4d | P=%.4f R=%.4f F1=%.4f AP50=%.4f"
              % (name, d["gt"], d["tp"], d["fp"], d["fn"], p_, r_, f1, a))
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print("report:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
