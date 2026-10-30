#!/usr/bin/env python3
"""Convert the V3 3-class YOLO to RKNN for RK3576J (AFH03).

RUN THIS ON A LINUX x86_64 MACHINE WITH rknn-toolkit2 INSTALLED.
(rknn-toolkit2 has no Windows / Python 3.12 wheel - see PREP_STATUS.md.)

    python3 convert_v3_to_rknn.py --onnx ... --calib calib/list.txt --out out/
    python3 convert_v3_to_rknn.py --onnx ... --calib calib/list.txt --out out/ --fp16-only

What it does
  1. loads the ONNX, prints the operator histogram and the input/output tensors
  2. builds an FP16 RKNN (do_quantization=False) and an INT8 RKNN (do_quantization=True)
  3. reports each model's build log and output shapes
  4. with --eval-dir it also runs the RKNN simulator over a YOLO-split and prints per-class
     precision / recall / F1 so the INT8 accuracy can be checked against the FP32 baseline

Class order is NEVER changed: 0=ball, 1=hand, 2=racket. Input is always Gray8 replicated to
3 channels, letterboxed with pad 114, /255, NCHW float32 - the same contract as the ONNX.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys

import numpy as np

CLASSES = {0: "ball", 1: "hand", 2: "racket"}
CONF = {0: 0.20, 1: 0.25, 2: 0.25}
PAD = 114


def log(msg: str) -> None:
    print(msg, flush=True)


def preprocess(gray: np.ndarray, size: int):
    """GRAY8 -> letterboxed NHWC uint8 (what RKNN wants) + the inverse mapping."""
    import cv2
    h, w = gray.shape[:2]
    s = min(size / w, size / h)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    rs = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size), PAD, np.uint8)
    px, py = (size - nw) // 2, (size - nh) // 2
    canvas[py:py + nh, px:px + nw] = rs
    # Gray3 = three identical channels -> NHWC uint8; 'mean_values=[0,0,0] scale=[255,255,255]'
    # in RKNN config does the /255, so we must NOT divide here.
    return np.ascontiguousarray(np.dstack([canvas, canvas, canvas])[None]), s, px, py


def decode(out: np.ndarray, s, px, py, w0, h0, conf, iou=0.5, max_det=60):
    """out: [7, N] -> detections in ORIGINAL image pixels (x1,y1,x2,y2)."""
    scores = out[4:]
    cls = scores.argmax(axis=0)
    sc = scores.max(axis=0)
    keep = [c for c in range(3) if (cls == c).any()]
    dets = []
    for c in keep:
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
        for i, a, bb, cc, dd in zip(idx, x1, y1, x2, y2):
            if cc - a < 1 or dd - bb < 1:
                continue
            cand = [float(a), float(bb), float(cc), float(dd)]
            dup = False
            for k in kept:
                iw = max(0.0, min(cand[2], k[2]) - max(cand[0], k[0]))
                ih = max(0.0, min(cand[3], k[3]) - max(cand[1], k[1]))
                inter = iw * ih
                if inter > 0:
                    ua = ((cand[2] - cand[0]) * (cand[3] - cand[1])
                          + (k[2] - k[0]) * (k[3] - k[1]) - inter)
                    if ua > 0 and inter / ua > iou:
                        dup = True
                        break
            if not dup:
                kept.append(cand + [float(sc[i]), c])
            if len(kept) >= max_det:
                break
        dets.extend(kept)
    dets.sort(key=lambda t: -t[4])
    return dets


def build(onnx_path: str, out_path: str, calib_list: str | None, int8: bool, target: str,
          core_mask: str | None):
    from rknn.api import RKNN
    rknn = RKNN(verbose=True)
    kw = dict(target_platform=target, mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]],
              optimization_level=3)
    if core_mask:
        kw["core_mask"] = core_mask
    rknn.config(**kw)
    if rknn.load_onnx(model=onnx_path) != 0:
        raise SystemExit("load_onnx failed")
    ret = rknn.build(do_quantization=int8, dataset=calib_list if int8 else None)
    if ret != 0:
        raise SystemExit("build failed (INT8=%s)" % int8)
    if rknn.export_rknn(out_path) != 0:
        raise SystemExit("export_rknn failed")
    log("wrote %s" % out_path)
    return rknn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", help="path to the single-output ONNX")
    ap.add_argument("--out", default="out", help="output dir")
    ap.add_argument("--calib", default=None)
    ap.add_argument("--fp16-only", action="store_true")
    ap.add_argument("--target", default="rk3576")
    ap.add_argument("--core-mask", default=None, help="auto|0|1|0_1|all (runtime also settable)")
    ap.add_argument("--eval-dir", default=None, help="YOLO split dir with images/val + labels/val")
    ap.add_argument("--config", default=None, help="YAML: configs/fp16_960.yaml or configs/int8_960.yaml")
    args = ap.parse_args()

    if args.config:
        import yaml
        cfg_path = pathlib.Path(args.config).resolve()
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        root = cfg_path.parent.parent            # configs/ -> package root
        def _p(v):
            if not v:
                return None
            q = pathlib.Path(str(v))
            return str(q if q.is_absolute() else root / q)
        if cfg.get("onnx"):
            args.onnx = _p(cfg["onnx"])
        if cfg.get("out"):
            args.out = str(pathlib.Path(_p(cfg["out"])).parent)
        if cfg.get("dataset"):
            args.calib = _p(cfg["dataset"])
        if cfg.get("eval_dir"):
            args.eval_dir = str(cfg["eval_dir"])
        if cfg.get("target_platform"):
            args.target = cfg["target_platform"]
        args.fp16_only = not bool(cfg.get("quantized", False))
        log("config: quantized=%s  onnx=%s  out=%s  calib=%s"
            % (not args.fp16_only, args.onnx, args.out, args.calib))
    if not args.onnx:
        raise SystemExit("--onnx or --config is required")

    import onnx
    m = onnx.load(args.onnx)
    ops = {}
    for n in m.graph.node:
        ops[n.op_type] = ops.get(n.op_type, 0) + 1
    log("ONNX ops: " + ", ".join("%s=%d" % kv for kv in sorted(ops.items(), key=lambda kv: -kv[1])))
    log("inputs: " + str([(i.name, [d.dim_value for d in i.type.tensor_type.shape.dim]) for i in m.graph.input]))
    log("outputs: " + str([o.name for o in m.graph.output]))
    if len(m.graph.output) != 1:
        log("WARNING: graph has %d outputs; use the single-output export "
            "(pingpong_yolov8n_gray_3cls_v3_960_single_out.onnx)" % len(m.graph.output))

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = pathlib.Path(args.onnx).stem

    build(args.onnx, str(outdir / (stem + "_fp16.rknn")), None, False, args.target, args.core_mask)
    if not args.fp16_only:
        if not args.calib:
            raise SystemExit("--calib is required for INT8")
        build(args.onnx, str(outdir / (stem + "_int8.rknn")), args.calib, True, args.target,
              args.core_mask)

    if args.eval_dir:
        evaluate(outdir / (stem + "_int8.rknn" if not args.fp16_only else stem + "_fp16.rknn"),
                 args.onnx, pathlib.Path(args.eval_dir))
    return 0


def evaluate(rknn_path: pathlib.Path, onnx_path: str, d: pathlib.Path) -> None:
    """Per-class precision/recall/F1 on the RKNN simulator."""
    from rknn.api import RKNN
    import cv2
    rknn = RKNN()
    rknn.load_rknn(str(rknn_path))
    rknn.init_runtime()
    size = 960
    stats = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CLASSES}
    for p in sorted((d / "images/val").glob("*.jpg")):
        lp = d / "labels/val" / (p.stem + ".txt")
        if not lp.is_file():
            continue
        buf = np.fromfile(str(p), dtype=np.uint8)
        g = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
        h, w = g.shape[:2]
        gts = {}
        for ln in lp.read_text(errors="replace").splitlines():
            t = ln.split()
            if len(t) < 5:
                continue
            c = int(float(t[0]))
            cx, cy, bw, bh = (float(v) for v in t[1:5])
            gts.setdefault(c, []).append([(cx - bw / 2) * w, (cy - bh / 2) * h,
                                          (cx + bw / 2) * w, (cy + bh / 2) * h])
        x, s, px, py = preprocess(g, size)
        outs = rknn.inference(inputs=[x])[0]
        dets = decode(np.array(outs)[0] if np.array(outs).ndim == 3 else np.array(outs), s, px, py, w, h, CONF)
        for c in CLASSES:
            gl = gts.get(c, [])
            used = set()
            for det in [t for t in dets if t[5] == c]:
                best, bi = 0.0, -1
                for k, gg in enumerate(gl):
                    if k in used:
                        continue
                    iw = max(0.0, min(det[2], gg[2]) - max(det[0], gg[0]))
                    ih = max(0.0, min(det[3], gg[3]) - max(det[1], gg[1]))
                    inter = iw * ih
                    ua = (det[2] - det[0]) * (det[3] - det[1]) + (gg[2] - gg[0]) * (gg[3] - gg[1]) - inter
                    v = inter / ua if ua > 0 else 0.0
                    if v > best:
                        best, bi = v, k
                if bi >= 0 and best >= 0.5:
                    used.add(bi)
                    stats[c]["tp"] += 1
                else:
                    stats[c]["fp"] += 1
            stats[c]["fn"] += len(gl) - len(used)
    rows = []
    for c, name in CLASSES.items():
        tp, fp, fn = stats[c]["tp"], stats[c]["fp"], stats[c]["fn"]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        rows.append({"class": name, "tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4),
                     "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0})
        log("  %-7s TP=%4d FP=%4d FN=%4d P=%.4f R=%.4f F1=%.4f" % (name, tp, fp, fn, p, r, rows[-1]["f1"]))
    with open(rknn_path.with_suffix(".accuracy.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    sys.exit(main())
