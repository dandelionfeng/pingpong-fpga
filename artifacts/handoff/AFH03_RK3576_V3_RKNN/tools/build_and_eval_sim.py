#!/usr/bin/env python3
"""Build + evaluate an RKNN model on the PC simulator in ONE process.

rknn-toolkit2 refuses simulator inference on a model that was reloaded with load_rknn
("RKNN model that loaded by 'load_rknn' not support inference on the simulator"), and the
simulator does not accept target_platform='rk3576'. So the flow is:

    config(target_platform=<simulator-supported>) -> load_onnx -> build -> init_runtime() -> infer

Passing --platform rk3588 therefore measures the *quantisation loss* of the same ONNX with the
same calibration set on a numerically comparable target. That number is a PROXY for rk3576:
it is not the rk3576 artefact and it is not an on-board measurement.

Usage:
  python3 build_and_eval_sim.py --onnx v3_six_out.onnx --platform rk3588 --int8 \
      --calib calib_list_linux.txt --val val_imgs --labels val_labels --limit 300
"""
from __future__ import annotations

import argparse
import json
import pathlib
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
    return np.dstack([canvas, canvas, canvas])[None], s, px, py


def iou(a, b):
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def decode(out, s, px, py, w0, h0, conf, nms=0.5, max_det=60):
    scores = out[4:]
    cls = scores.argmax(axis=0)
    sc = scores.max(axis=0)
    dets = []
    for c in (0, 1, 2):
        idx = np.nonzero((cls == c) & (sc >= conf[c]))[0]
        if idx.size == 0:
            continue
        idx = idx[np.argsort(-sc[idx])][: max_det * 10]
        b = out[:4, idx]
        x1 = np.clip((b[0] - b[2] / 2 - px) / s, 0, w0)
        y1 = np.clip((b[1] - b[3] / 2 - py) / s, 0, h0)
        x2 = np.clip((b[0] + b[2] / 2 - px) / s, 0, w0)
        y2 = np.clip((b[1] + b[3] / 2 - py) / s, 0, h0)
        kept = []
        for a, bb, cc, dd, s_ in zip(x1, y1, x2, y2, sc[idx]):
            if cc - a < 1 or dd - bb < 1:
                continue
            cand = [float(a), float(bb), float(cc), float(dd)]
            if all(iou(cand, k) <= nms for k in kept):
                kept.append(cand + [float(s_), c])
            if len(kept) >= max_det:
                break
        dets.extend(kept)
    return dets


def ap50(pairs, n_gt):
    if n_gt == 0:
        return 0.0
    pairs = sorted(pairs, key=lambda t: -t[0])
    tp = fp = 0
    rec, prec = [0.0], [1.0]
    for _, is_tp in pairs:
        tp += 1 if is_tp else 0
        fp += 0 if is_tp else 1
        rec.append(tp / n_gt)
        prec.append(tp / (tp + fp))
    for i in range(len(prec) - 2, -1, -1):
        prec[i] = max(prec[i], prec[i + 1])
    return sum((rec[i] - rec[i - 1]) * prec[i] for i in range(1, len(rec)) if rec[i] != rec[i - 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--platform", default="rk3588", help="simulator-supported platform (proxy)")
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--calib", default=None)
    ap.add_argument("--val", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tag", default="model")
    ap.add_argument("--save-rknn", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from rknn.api import RKNN
    r = RKNN(verbose=False)
    r.config(target_platform=args.platform, mean_values=[[0, 0, 0]],
             std_values=[[255, 255, 255]], optimization_level=3)
    if r.load_onnx(model=args.onnx) != 0:
        raise SystemExit("load_onnx failed")
    ret = r.build(do_quantization=args.int8, dataset=args.calib if args.int8 else None)
    print("build ret =", ret, flush=True)
    if ret != 0:
        raise SystemExit(1)
    if args.save_rknn:
        r.export_rknn(args.save_rknn)
        print("saved", args.save_rknn, flush=True)
    if r.init_runtime() != 0:
        raise SystemExit("init_runtime failed")

    files = sorted(pathlib.Path(args.val).glob("*.jpg"))
    if args.limit:
        files = files[: args.limit]
    per = {c: {"tp": 0, "fp": 0, "fn": 0, "gt": 0, "pairs": []} for c in NAMES}
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
        outs = r.inference(inputs=[x])
        target = None
        for o in outs:
            a = np.array(o)
            if a.ndim == 3 and a.shape[1] == 7:
                target = a[0]
                break
            if a.ndim == 2 and a.shape[0] == 7:
                target = a
                break
        if target is None:
            print("no [7,N] output:", [np.array(o).shape for o in outs])
            return 2
        dets = decode(target, s, px, py, w, h, CONF)
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
        if n % 50 == 0:
            print("  %d/%d" % (n, len(files)), flush=True)

    rep = {"tag": args.tag, "platform": args.platform, "int8": args.int8,
           "images": n, "conf": CONF, "classes": {}}
    print("=== %s | platform=%s int8=%s | %d images (SIMULATOR) ==="
          % (args.tag, args.platform, args.int8, n))
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
