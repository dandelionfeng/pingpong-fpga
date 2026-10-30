"""Build the V9 2-class (ball, hand) dataset.

Label-completeness facts for the source set (measured):
  tt/tt2 : 989 frames with ball, 0 frames with hand   <- hands are everywhere but unlabelled
  ps     : 521 ball frames, 436 with rule-based hand candidates
  bh/pp/sy: 1500 hand frames, no ball (close-up film frames, no ball present)
  bg/hn  : 300 negatives

Training a 2-class model on that as-is would teach "hand = background" on the 2,110 wide
tabletennis frames, which is exactly the failure mode the task forbids. Since the V3 model already
detects hands with P 0.69, we run it on those frames and add its confident hand boxes as
AUTO_ASSISTED candidates (conf >= 0.45). Ball labels are NOT touched (they are already QC'd), and
nothing is invented for racket because racket no longer exists in this model.

Every generated label line is tagged in the manifest so the provenance is auditable.
"""
from __future__ import annotations

import collections
import json
import os
import pathlib
import shutil
import sys
import time

import numpy as np

ROOT = pathlib.Path(r"D:\电脑管家迁移文件\xwechat_files\wxid_ttrefx9qt9o722_32d9\msg\file\2026-10\方案及分工\方案及分工\pingpong-fpga")
SRC = ROOT / "artifacts/files/datasets/pingpong_unified_3cls_v4"
V3_ONNX = ROOT / "artifacts/files/models/unified_3cls_v3b/pingpong_yolov8n_gray_3cls_v3_960_960.onnx"
OUT = ROOT / "artifacts/files/datasets/pingpong_v9_ball_hand"
NL = chr(10)
HAND_CONF = 0.45


def say(t):
    sys.stdout.buffer.write((t + NL).encode("utf-8", "replace"))
    sys.stdout.flush()


def main() -> int:
    sys.path.insert(0, str(ROOT / "tmp"))
    import eval_racket as ER
    import eval_unified_3cls as EU
    import onnxruntime as ort

    if OUT.is_dir():
        shutil.rmtree(OUT)
    for s in ("train", "val"):
        (OUT / "images" / s).mkdir(parents=True, exist_ok=True)
        (OUT / "labels" / s).mkdir(parents=True, exist_ok=True)

    sess = ort.InferenceSession(str(V3_ONNX), providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name
    size = int(sess.get_inputs()[0].shape[2])

    stats = collections.Counter()
    manifest = []
    t0 = time.time()

    for split in ("train", "val"):
        for p in sorted((SRC / "images" / split).glob("*.jpg")):
            lp = SRC / "labels" / split / (p.stem + ".txt")
            if not lp.is_file():
                continue
            pre = p.stem.split("_")[0]
            balls, hands = [], []
            for ln in lp.read_text(errors="replace").splitlines():
                t = ln.split()
                if len(t) < 5:
                    continue
                c = int(float(t[0]))
                if c == 0:
                    balls.append(ln)
                elif c == 1:
                    hands.append(ln)
            src_hand = "gt"
            if split == "train" and pre in ("tt", "tt2") and not hands:
                # no hand labels at all on the wide tabletennis frames -> ask V3
                g = ER.read_gray(p)
                if g is not None:
                    h, w = g.shape[:2]
                    x, s, px, py = ER.letterbox_gray3(g, size)
                    o = sess.run(None, {iname: x})[0][0]
                    dets = EU.decode_all(o, s, px, py, w, h)
                    for d in dets:
                        if d["cls"] != 1 or d["score"] < HAND_CONF:
                            continue
                        x1, y1, x2, y2 = d["xyxy"]
                        hands.append("1 %.6f %.6f %.6f %.6f" % ((x1 + x2) / 2 / w, (y1 + y2) / 2 / h,
                                                                (x2 - x1) / w, (y2 - y1) / h))
                    src_hand = "auto_v3" if hands else "none_found"
            elif hands:
                src_hand = "gt_or_candidate"

            lines = balls + hands
            dst_img = OUT / "images" / split / p.name
            try:
                os.link(p, dst_img)
            except OSError:
                shutil.copy2(p, dst_img)
            (OUT / "labels" / split / (p.stem + ".txt")).write_text(
                (NL.join(lines) + NL) if lines else "", encoding="utf-8")
            stats[(split, "ball_frames")] += bool(balls)
            stats[(split, "hand_frames")] += bool(hands)
            stats[(split, "empty")] += (not lines)
            stats[(split, "auto_hand_frames")] += (src_hand == "auto_v3")
            manifest.append({"split": split, "file": p.stem, "source": pre,
                             "ball_boxes": len(balls), "hand_boxes": len(hands),
                             "hand_provenance": src_hand})
            if len(manifest) % 500 == 0:
                say("  %d frames..." % len(manifest))

    (OUT / "data.yaml").write_text(
        "path: " + OUT.resolve().as_posix() + NL + "train: images/train" + NL
        + "val: images/val" + NL + "nc: 2" + NL + "names:" + NL
        + "  0: ball" + NL + "  1: hand" + NL, encoding="utf-8")

    boxes = collections.Counter()
    for split in ("train", "val"):
        for lp in (OUT / "labels" / split).glob("*.txt"):
            for ln in lp.read_text(errors="replace").splitlines():
                t = ln.split()
                if len(t) >= 5:
                    boxes[(split, int(float(t[0])))] += 1
            boxes[(split, "frames")] += 1

    rep = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": str(SRC.relative_to(ROOT)),
           "classes": {"0": "ball", "1": "hand"},
           "hand_autolabel": {"model": str(V3_ONNX.relative_to(ROOT)), "conf": HAND_CONF,
                              "applies_to": "tt/tt2 train frames only",
                              "status": "AUTO_ASSISTED_HAND_CANDIDATE - not human labels"},
           "counts": {("%s_%s" % k): v for k, v in sorted(stats.items(), key=lambda kv: str(kv[0]))},
           "boxes": {("%s_%s" % k): v for k, v in sorted(boxes.items(), key=lambda kv: str(kv[0]))},
           "manifest": manifest}
    (OUT / "build_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    say(json.dumps({"counts": rep["counts"], "boxes": rep["boxes"]}, ensure_ascii=False))
    say("elapsed %.0fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
