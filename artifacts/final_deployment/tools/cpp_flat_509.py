#!/usr/bin/env python3
"""509-image regression using the C++ flat-DFL decoder via ctypes.

The C++ decoder is compiled from dfl_flat_decoder.hpp; ONNX supplies the same
DFL/logit tensors that RKNN exposes. This validates C++ decode math, not NPU.
"""
from __future__ import annotations

import argparse
import ctypes
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


def nms(dets, limit=60):
    kept = []
    for d in sorted(dets, key=lambda t: -t[4]):
        if all(iou(d[:4], k[:4]) <= 0.5 for k in kept):
            kept.append(d)
        if len(kept) >= limit:
            break
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--lib", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--limit", type=int, default=509)
    ap.add_argument("--out", default="")
    ap.add_argument("--per-image", action="store_true")
    args = ap.parse_args()

    lib = ctypes.CDLL(args.lib)
    fp = ctypes.POINTER(ctypes.c_float)
    lib.c_flat_decode.argtypes = [fp, fp, fp, ctypes.c_int, ctypes.c_float, ctypes.c_int]
    lib.c_flat_decode.restype = ctypes.c_int

    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    files = sorted(pathlib.Path(args.val).glob("*.jpg"))[: args.limit]
    per = {c: {"tp": 0, "fp": 0, "fn": 0, "gt": 0, "pairs": []} for c in NAMES}
    per_image = []
    n = 0
    for p in files:
        g = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        h, w = g.shape[:2]
        gts = []
        lp = pathlib.Path(args.labels) / (p.stem + ".txt")
        for line in lp.read_text(errors="replace").splitlines() if lp.is_file() else []:
            t = line.split()
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
            return 2
        anchors = dfl.shape[1]
        out = np.zeros((7, anchors), np.float32)
        dfl = np.ascontiguousarray(dfl, np.float32)
        logits = np.ascontiguousarray(logits, np.float32)
        rc = lib.c_flat_decode(
            dfl.ctypes.data_as(fp), logits.ctypes.data_as(fp), out.ctypes.data_as(fp),
            anchors, -1.0, 0)
        if rc != 0:
            print("C++ decoder returned", rc)
            return 1
        xs, ys, ws, hs = out[0], out[1], out[2], out[3]
        scores = out[4:7]
        best_c = scores.argmax(axis=0)
        best = scores.max(axis=0)
        all_dets = []
        for c in NAMES:
            cand = []
            for i in np.nonzero((best_c == c) & (best >= CONF[c]))[0]:
                # C++ decoder contract matches the 6-head path: center xywh
                # in 960 letterbox coordinates.
                x1 = np.clip((xs[i] - ws[i] / 2 - px) / s, 0, w)
                y1 = np.clip((ys[i] - hs[i] / 2 - py) / s, 0, h)
                x2 = np.clip((xs[i] + ws[i] / 2 - px) / s, 0, w)
                y2 = np.clip((ys[i] + hs[i] / 2 - py) / s, 0, h)
                if x2 - x1 >= 1 and y2 - y1 >= 1:
                    cand.append([float(x1), float(y1), float(x2), float(y2), float(best[i]), c])
            dets = nms(cand)
            gl = [b for (cc, b) in gts if cc == c]
            per[c]["gt"] += len(gl)
            used = set()
            for d in dets:
                best_iou, bi = 0.0, -1
                for k, gg in enumerate(gl):
                    if k in used:
                        continue
                    v = iou(d[:4], gg)
                    if v > best_iou:
                        best_iou, bi = v, k
                if bi >= 0 and best_iou >= 0.5:
                    used.add(bi)
                    per[c]["tp"] += 1
                    per[c]["pairs"].append((d[4], True))
                else:
                    per[c]["fp"] += 1
                    per[c]["pairs"].append((d[4], False))
            per[c]["fn"] += len(gl) - len(used)
            all_dets.extend(dets)
        if args.per_image:
            per_image.append({
                "file": p.name,
                "detections": [
                    {"class": NAMES[d[5]], "confidence": round(d[4], 6),
                     "bbox_xyxy": [round(v, 3) for v in d[:4]]}
                    for d in all_dets
                ],
            })
        n += 1
        if n % 100 == 0:
            print(f"  {n}/{len(files)}", flush=True)

    rep = {"tag": "cpp_flat_dfl_509", "images": n, "classes": {}}
    for c, name in NAMES.items():
        d = per[c]
        p_ = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else 0.0
        r_ = d["tp"] / (d["tp"] + d["fn"]) if d["tp"] + d["fn"] else 0.0
        f1 = 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0
        a = ap50(d["pairs"], d["gt"])
        rep["classes"][name] = {"gt": d["gt"], "tp": d["tp"], "fp": d["fp"], "fn": d["fn"],
                                "precision": round(p_, 4), "recall": round(r_, 4),
                                "f1": round(f1, 4), "ap50": round(a, 4)}
        print(f"  {name:7s} GT={d['gt']:4d} TP={d['tp']:4d} FP={d['fp']:4d} FN={d['fn']:4d} "
              f"P={p_:.4f} R={r_:.4f} F1={f1:.4f} AP50={a:.4f}")
    if args.per_image:
        rep["per_image"] = per_image
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
