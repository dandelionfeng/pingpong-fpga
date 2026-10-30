#!/usr/bin/env python3
"""Build the INT8 calibration list for the V3 3-class model (RUN ON THE PC, output is text only).

Rules enforced here:
  * calibration images come from the TRAIN split only - the validation split is never used,
    because it is the only accuracy yardstick we have and must stay untouched
  * the list is stratified so the quantizer sees every class and every scene type:
    ball-bearing frames, hand-dominant frames, racket-heavy frames and empty frames
  * images are copied as-is (GRAY8 sources); the conversion script replicates gray->gray3, so
    the calibration data fed to the quantizer has exactly the deployment statistics
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import random
import shutil

NAMES = {0: "ball", 1: "hand", 2: "racket"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="YOLO dir with images/train + labels/train")
    ap.add_argument("--out", default="calib")
    ap.add_argument("--per-bucket", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    d = pathlib.Path(args.dataset)
    out = pathlib.Path(args.out)
    if out.is_dir():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)

    rnd = random.Random(args.seed)
    buckets = collections.defaultdict(list)
    for lp in sorted((d / "labels/train").glob("*.txt")):
        img = d / "images/train" / (lp.stem + ".jpg")
        if not img.is_file():
            continue
        cls = {int(float(l.split()[0])) for l in lp.read_text(errors="replace").splitlines() if len(l.split()) >= 5}
        if not cls:
            key = "empty"
        elif 0 in cls and 2 in cls:
            key = "ball_racket"
        elif 0 in cls:
            key = "ball_only"
        elif 1 in cls and 2 not in cls:
            key = "hand_only"
        elif 2 in cls:
            key = "racket_other"
        else:
            key = "misc"
        buckets[key].append(img)

    lines, counts = [], {}
    for key, imgs in sorted(buckets.items()):
        rnd.shuffle(imgs)
        pick = imgs[: args.per_bucket]
        counts[key] = len(pick)
        for p in pick:
            dst = out / "images" / p.name
            if not dst.exists():
                shutil.copy2(p, dst)
            lines.append(dst.resolve().as_posix())

    (out / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("calibration images:", len(lines), "by bucket:", counts)
    print("list:", (out / "list.txt").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
