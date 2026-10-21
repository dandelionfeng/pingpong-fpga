#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Score the JSONL predictions produced by eval_ball_models.py against the bundled GT.

Matching rules are identical to the rules used throughout this project's ball work:
  * one-to-one greedy match by IoU >= 0.5, highest-score detections first
  * a frame is a "hit" when the matched ball centre is within 50 px of the GT centre
  * centre error is only computed on matched detections
  * AP50 uses the 101-point interpolated precision-recall curve

Usage
  python tools/eval_ball_models.py --model ball_yolo_v1_1280 --source ../gt/images --out ../out/v1
  python tools/score_ball_models.py --predictions ../out/v1/predictions.jsonl --conf 0.10
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

PKG = pathlib.Path(__file__).resolve().parent.parent
GT_JSON = PKG / "gt" / "annotations_json"
HIT_PX = 50.0


def iou(a, b) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def centre(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def ap50(preds, n_gt: int) -> float:
    """preds: list of (score, tp_flag). 101-point interpolation."""
    if n_gt == 0:
        return 0.0
    preds = sorted(preds, key=lambda x: -x[0])
    tp = fp = 0
    rec, prec = [], []
    for _score, is_tp in preds:
        if is_tp:
            tp += 1
        else:
            fp += 1
        rec.append(tp / n_gt)
        prec.append(tp / max(1, tp + fp))
    mrec = [0.0] + rec + [1.0]
    mpre = [0.0] + prec + [0.0]
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    out = 0.0
    for t in range(101):
        x = t / 100.0
        p = 0.0
        for i in range(len(mrec) - 1):
            if mrec[i] <= x <= mrec[i + 1] and mrec[i + 1] > mrec[i]:
                p = mpre[i + 1]
                break
        out += p
    return out / 101.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Score ball YOLO predictions against the bundled GT.")
    ap.add_argument("--predictions", required=True, help="predictions.jsonl from eval_ball_models.py")
    ap.add_argument("--conf", type=float, default=0.10, help="score threshold")
    ap.add_argument("--hit-px", type=float, default=HIT_PX)
    ap.add_argument("--dump-misses", action="store_true", help="print per-frame misses")
    args = ap.parse_args()

    pred_path = pathlib.Path(args.predictions)
    if not pred_path.is_file():
        sys.stderr.write("ERROR: predictions not found: %s\n" % pred_path)
        return 2
    recs = {}
    for line in pred_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["image"]] = r

    gts = {}
    for jp in sorted(GT_JSON.glob("*.json")):
        g = json.loads(jp.read_text(encoding="utf-8"))
        balls = [o["bbox_xyxy"] for o in g.get("objects", [])
                 if str(o.get("class_name", "")).lower() == "ball"]
        gts[g["image_id"] + ".jpg"] = balls
    if not gts:
        sys.stderr.write("ERROR: no GT json found under %s\n" % GT_JSON)
        return 2

    tp = fp = fn = 0
    hits = 0
    with_ball = 0
    empty_frames = 0
    empty_fp = 0
    errs = []
    ap_preds = []
    missing = []
    for name, balls in sorted(gts.items()):
        r = recs.get(name)
        if r is None:
            missing.append(name)
            continue
        dets = [d for d in r["detections"] if d["score"] >= args.conf]
        dets.sort(key=lambda d: -d["score"])
        if balls:
            with_ball += 1
        else:
            empty_frames += 1
        used = set()
        frame_hit = False
        for d in dets:
            best, best_iou = -1, 0.0
            for i, b in enumerate(balls):
                if i in used:
                    continue
                v = iou(d["xyxy"], b)
                if v > best_iou:
                    best, best_iou = i, v
            if best >= 0 and best_iou >= 0.5:
                used.add(best)
                tp += 1
                ap_preds.append((d["score"], True))
                dc, gc = centre(d["xyxy"]), centre(balls[best])
                dist = ((dc[0] - gc[0]) ** 2 + (dc[1] - gc[1]) ** 2) ** 0.5
                errs.append(dist)
                if dist <= args.hit_px:
                    frame_hit = True
            else:
                fp += 1
                ap_preds.append((d["score"], False))
                if not balls:
                    empty_fp += 1
        fn += len(balls) - len(used)
        if frame_hit:
            hits += 1
        elif args.dump_misses:
            print("  miss %-58s dets=%d" % (name, len(dets)))

    errs.sort()
    def pct(v, q):
        return round(v[min(len(v) - 1, int(len(v) * q))], 2) if v else None

    n_gt = sum(len(b) for b in gts.values())
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r_ = tp / n_gt if n_gt else 0.0
    f1 = 2 * p * r_ / (p + r_) if (p + r_) else 0.0
    print(json.dumps({
        "predictions": str(pred_path),
        "conf": args.conf,
        "gt_images": len(gts), "gt_ball_boxes": n_gt,
        "frames_with_ball": with_ball, "empty_frames": empty_frames,
        "evaluated_images": len(recs), "missing_predictions": len(missing),
        "hit_within_%dpx" % int(args.hit_px): hits,
        "hit_rate": round(hits / with_ball, 4) if with_ball else None,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(p, 4), "recall": round(r_, 4), "f1": round(f1, 4),
        "ap50": round(ap50(ap_preds, n_gt), 4),
        "centre_err_median_px": pct(errs, 0.5), "centre_err_p90_px": pct(errs, 0.9),
        "empty_frame_fp_boxes": empty_fp,
    }, ensure_ascii=False, indent=2))
    if missing:
        print("WARNING: %d GT images had no prediction record (e.g. %s)"
              % (len(missing), missing[:3]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
