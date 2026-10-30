#!/usr/bin/env python3
"""Prove that class filtering changes nothing for ball/hand on the fixed 509-frame val.

Runs the V3 ONNX twice per frame with identical preprocessing:
  A. decode all 3 classes + NMS                      (unfiltered, the current pipeline)
  B. identical decode, then drop class 2 (racket)     (what this package ships)
and compares per-class TP/FP/FN, P/R/F1/AP50, plus the postprocess wall time of each variant.

The filter runs AFTER decoding and NMS, exactly like the C++ program, so any difference in the
ball/hand numbers would mean a bug in the filter itself.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tmp"))
import eval_racket as ER  # noqa: E402
import eval_unified_3cls as EU  # noqa: E402

NAMES = {0: "ball", 1: "hand", 2: "racket"}
CONF = {0: 0.20, 1: 0.25, 2: 0.25}
KEEP = {0, 1}          # ball + hand; 2 (racket) is filtered
SIZE = 960


def decode_all(raw, s, px, py, w0, h0, conf):
    """Decode all three classes with per-class NMS (identical code for both variants)."""
    scores = raw[4:]
    cls = scores.argmax(axis=0)
    sc = scores.max(axis=0)
    dets = []
    for c in (0, 1, 2):
        idx = np.nonzero((cls == c) & (sc >= conf[c]))[0]
        if idx.size == 0:
            continue
        idx = idx[np.argsort(-sc[idx])][:600]
        b = raw[:4, idx]
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
                    ua = ((cand[2] - cand[0]) * (cand[3] - cand[1])
                          + (k[2] - k[0]) * (k[3] - k[1]) - inter)
                    if ua > 0 and inter / ua > 0.5:
                        ok = False
                        break
            if ok:
                kept.append(cand + [float(s_), c])
            if len(kept) >= 60:
                break
        dets.extend(kept)
    return dets


def filter_classes(dets, keep=KEEP):
    """The filter under test: drop detections whose class is not in `keep`."""
    return [d for d in dets if d[5] in keep]


def metrics(det_lists, items):
    rep = {}
    for cid, name in NAMES.items():
        n_gt = sum(1 for it in items for (c, _) in it["gts"] if c == cid)
        TP = FP = FN = 0
        pairs = []
        for d, it in zip(det_lists, items):
            gts = [b for (c, b) in it["gts"] if c == cid]
            keep = [x for x in d if x[5] == cid]
            used = set()
            for det in keep:
                best, bi = 0.0, -1
                for i, g in enumerate(gts):
                    if i in used:
                        continue
                    v = ER.iou(det[:4], g)
                    if v > best:
                        best, bi = v, i
                if bi >= 0 and best >= 0.5:
                    used.add(bi)
                    TP += 1
                    pairs.append((det[4], True))
                else:
                    FP += 1
                    pairs.append((det[4], False))
            FN += len(gts) - len(used)
        p = TP / (TP + FP) if TP + FP else 0.0
        r = TP / (TP + FN) if TP + FN else 0.0
        rep[name] = {"gt": n_gt, "tp": TP, "fp": FP, "fn": FN,
                     "precision": round(p, 4), "recall": round(r, 4),
                     "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
                     "ap50": round(ER.ap_from_pairs(pairs, n_gt), 4) if n_gt else None}
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"], sess_options=so)
    iname = sess.get_inputs()[0].name
    items = EU.load_gt(pathlib.Path(args.dataset), "val")

    dets_a, dets_b = [], []
    t_post_a, t_post_b = [], []
    racket_in_a = racket_in_b = 0
    identical_frames = 0
    for it in items:
        g = it["gray"]
        w0, h0 = g.shape[1], g.shape[0]
        x, s, px, py = ER.letterbox_gray3(g, SIZE)
        raw = sess.run(None, {iname: x})[0][0]

        t0 = time.perf_counter()
        a = decode_all(raw, s, px, py, w0, h0, CONF)
        t1 = time.perf_counter()

        b = filter_classes(a)
        t2 = time.perf_counter()

        dets_a.append(a)
        dets_b.append(b)
        t_post_a.append((t1 - t0) * 1000)
        t_post_b.append((t2 - t1) * 1000)
        racket_in_a += sum(1 for d in a if d[5] == 2)
        racket_in_b += sum(1 for d in b if d[5] == 2)
        # the kept detections must be literally the same objects
        if [d for d in a if d[5] in KEEP] == b:
            identical_frames += 1

    rep = {"onnx": args.onnx, "images": len(items),
           "unfiltered": metrics(dets_a, items),
           "filtered": metrics(dets_b, items),
           "racket_detections": {"unfiltered": racket_in_a, "filtered": racket_in_b},
           "frames_with_identical_kept_detections": identical_frames,
           "postprocess_ms": {"decode_nms_all3": round(statistics.mean(t_post_a), 3),
                              "filter_pass": round(statistics.mean(t_post_b), 4),
                              "median_decode_nms_all3": round(statistics.median(t_post_a), 3)}}

    print("=== unfiltered (3 classes) ===")
    for k, v in rep["unfiltered"].items():
        print("  %-6s GT=%4d TP=%4d FP=%4d FN=%4d | P=%.4f R=%.4f F1=%.4f AP50=%s"
              % (k, v["gt"], v["tp"], v["fp"], v["fn"], v["precision"], v["recall"], v["f1"], v["ap50"]))
    print("=== filtered (ball + hand) ===")
    for k, v in rep["filtered"].items():
        print("  %-6s GT=%4d TP=%4d FP=%4d FN=%4d | P=%.4f R=%.4f F1=%.4f AP50=%s"
              % (k, v["gt"], v["tp"], v["fp"], v["fn"], v["precision"], v["recall"], v["f1"], v["ap50"]))
    print("racket detections: unfiltered=%d  filtered=%d" % (racket_in_a, racket_in_b))
    print("frames where kept detections are identical: %d/%d" % (identical_frames, len(items)))
    print("postprocess: decode+NMS all 3 classes = %.3f ms | filter pass = %.4f ms"
          % (rep["postprocess_ms"]["decode_nms_all3"], rep["postprocess_ms"]["filter_pass"]))

    # hard assertions for the acceptance criteria
    for name in ("ball", "hand"):
        for f in ("tp", "fp", "fn", "precision", "recall", "f1", "ap50"):
            assert rep["unfiltered"][name][f] == rep["filtered"][name][f], \
                "%s.%s changed: %s -> %s" % (name, f, rep["unfiltered"][name][f],
                                             rep["filtered"][name][f])
    assert racket_in_b == 0, "racket still present in filtered output"
    assert identical_frames == len(items), "kept detections differ on some frames"
    print("ALL ASSERTIONS PASSED: ball/hand identical, no racket in output")

    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        print("report:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
