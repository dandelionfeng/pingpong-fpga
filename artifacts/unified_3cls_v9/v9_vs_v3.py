#!/usr/bin/env python3
"""V9 (2-class) vs V3 (3-class) - identical evaluation on the fixed 509-frame val.

Reports per class: TP/FP/FN, P/R/F1/AP50, plus ball recall split by GT box width, parameter count
and CPU latency. Racket GT is ignored for V9 (that class no longer exists).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tmp"))
import eval_racket as ER  # noqa: E402
import eval_unified_3cls as EU  # noqa: E402

NAMES = {0: "ball", 1: "hand"}
SIZE = 960


def letterbox(gray):
    return ER.letterbox_gray3(gray, SIZE)


def decode(out, s, px, py, w0, h0, conf, nms=0.5, max_det=60):
    scores = out[4:]
    cls = scores.argmax(axis=0)
    sc = scores.max(axis=0)
    dets = []
    for c in conf:
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
                kept.append(cand + [float(s_), c])
            if len(kept) >= max_det:
                break
        dets.extend(kept)
    return dets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v9", required=True)
    ap.add_argument("--v3", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    items = EU.load_gt(pathlib.Path(args.dataset), "val")
    CONF = {0: 0.20, 1: 0.25}

    res = {}
    for tag, path in (("v9_2cls", args.v9), ("v3_3cls", args.v3)):
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=so)
        iname = sess.get_inputs()[0].name
        lat = []
        per = {c: {"tp": 0, "fp": 0, "fn": 0, "gt": 0, "pairs": [], "gt_by_size": {}, "tp_by_size": {}}
               for c in NAMES}
        for it in items:
            g = it["gray"]
            w0, h0 = g.shape[1], g.shape[0]
            x, s, px, py = letterbox(g)
            t0 = time.perf_counter()
            o = sess.run(None, {iname: x})[0][0]
            lat.append((time.perf_counter() - t0) * 1000)
            dets = decode(o, s, px, py, w0, h0, CONF)
            for c in NAMES:
                gl = [b for (cc, b) in it["gts"] if cc == c]
                per[c]["gt"] += len(gl)
                used = set()
                for d in [t for t in dets if t[5] == c]:
                    best, bi = 0.0, -1
                    for k, gg in enumerate(gl):
                        if k in used:
                            continue
                        v = ER.iou(d[:4], gg)
                        if v > best:
                            best, bi = v, k
                    if bi >= 0 and best >= 0.5:
                        used.add(bi)
                        per[c]["tp"] += 1
                        per[c]["pairs"].append((d[4], True))
                        wpx = gl[bi][2] - gl[bi][0]
                        b = ("lt19" if wpx < 19 else "19_24" if wpx < 25 else
                             "25_34" if wpx < 35 else "ge35")
                        per[c]["gt_by_size"][b] = per[c]["gt_by_size"].get(b, 0) + 1
                        per[c]["tp_by_size"][b] = per[c]["tp_by_size"].get(b, 0) + 1
                    else:
                        per[c]["fp"] += 1
                        per[c]["pairs"].append((d[4], False))
                per[c]["fn"] += len(gl) - len(used)
                # count size buckets for the misses too
                for k, gg in enumerate(gl):
                    if k in used:
                        continue
                    wpx = gg[2] - gg[0]
                    b = ("lt19" if wpx < 19 else "19_24" if wpx < 25 else
                         "25_34" if wpx < 35 else "ge35")
                    per[c]["gt_by_size"][b] = per[c]["gt_by_size"].get(b, 0) + 1
        rep = {"model": tag, "onnx": path,
               "params": int(sum(np.prod(v.shape) for v in [np.zeros(1)]) if False else 0),
               "latency_ms_median": round(statistics.median(lat), 2),
               "classes": {}}
        for c, name in NAMES.items():
            d = per[c]
            p = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else 0.0
            r = d["tp"] / (d["tp"] + d["fn"]) if d["tp"] + d["fn"] else 0.0
            buckets = {}
            for b in ("lt19", "19_24", "25_34", "ge35"):
                g_n = d["gt_by_size"].get(b, 0)
                t_n = d["tp_by_size"].get(b, 0)
                if g_n:
                    buckets[b] = {"gt": g_n, "tp": t_n, "recall": round(t_n / g_n, 3)}
            rep["classes"][name] = {
                "gt": d["gt"], "tp": d["tp"], "fp": d["fp"], "fn": d["fn"],
                "precision": round(p, 4), "recall": round(r, 4),
                "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
                "ap50": round(ER.ap_from_pairs(d["pairs"], d["gt"]), 4),
                "recall_by_size": buckets}
        res[tag] = rep
        print("=== %s ===" % tag)
        for name, v in rep["classes"].items():
            print("  %-5s GT=%4d TP=%3d FP=%4d FN=%3d | P=%.4f R=%.4f F1=%.4f AP50=%.4f"
                  % (name, v["gt"], v["tp"], v["fp"], v["fn"], v["precision"], v["recall"],
                     v["f1"], v["ap50"]))
            print("        by size: " + json.dumps(v["recall_by_size"]))
        print("  median ONNX run: %.1f ms" % rep["latency_ms_median"])

    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
        print("report:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
