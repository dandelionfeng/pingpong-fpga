"""Temporal hand confirmation for the C perception outputs.

WHY THIS IS A SEPARATE HELPER
-----------------------------
The captain-facing C contract is frozen: the engine returns the RAW per-frame
hand detections and nothing else. This module consumes that output and adds a
video-level confirmation pass on top, so a consumer (module B, or an evaluation
harness) can opt into it without changing the C++ API or the DetectionResult
schema.

WHAT IT DOES
------------
Single-frame false positives are the dominant error mode of the hand detector.
A real hand is present for several consecutive frames and moves smoothly, so a
detection that appears for exactly one frame and vanishes is very likely noise.

The filter builds short tracks by greedy association and then keeps only tracks
that persist:

  * association: IoU >= iou_match, OR center distance <= center_match_k * the
    box diagonal (a small box may shift by more than an IoU allows while still
    being the same hand);
  * size guard: the box area ratio must stay within [1/max_size_ratio,
    max_size_ratio], which rejects a box that suddenly balloons or collapses;
  * a single-frame gap is tolerated (max_gap=1) so one missed frame does not
    break a real track;
  * a track is confirmed only when it spans at least `min_span` FRAMES (not
    detections) and contains at least `min_track_len` boxes. An isolated
    one-frame detection therefore never survives.

PARAMETERS
----------
The defaults below were FIXED BEFORE the evaluation set was touched and were
not tuned on it: they come from the same unsupervised gates used to mine the
pseudo positives (IoU 0.30 / center 0.60 * diagonal), plus the standard "allow a
one-frame dropout" rule. Do not tune them against BNDSTT_MANUAL_GT_V1.

NO ROLE LOGIC
-------------
This module never decides toss-hand vs racket-hand and never decides serve
legality. It only answers "is this box temporally persistent".
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

DEFAULTS = {
    "iou_match": 0.30,
    "center_match_k": 0.60,
    "max_size_ratio": 2.00,
    "max_gap": 1,
    "min_track_len": 2,
    "min_span": 2,
}


@dataclass
class Box:
    """Axis-aligned box in original eye pixels (C output convention)."""

    x: float
    y: float
    w: float
    h: float
    confidence: float = 1.0
    confirmed: bool = False

    @property
    def xyxy(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def diag(self) -> float:
        return math.hypot(self.w, self.h)

    @property
    def area(self) -> float:
        return abs(self.w * self.h)

    def as_dict(self) -> dict:
        return {"bbox": [self.x, self.y, self.w, self.h],
                "confidence": self.confidence}


def _iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a.xyxy
    bx1, by1, bx2, by2 = b.xyxy
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _center_dist(a: Box, b: Box) -> float:
    ax, ay = a.center
    bx, by = b.center
    return math.hypot(ax - bx, ay - by)


def is_match(a: Box, b: Box, iou_match: float = DEFAULTS["iou_match"],
             center_match_k: float = DEFAULTS["center_match_k"],
             max_size_ratio: float = DEFAULTS["max_size_ratio"]) -> bool:
    """True when two boxes plausibly belong to the same hand one frame apart."""
    if a.area <= 0 or b.area <= 0:
        return False
    ratio = a.area / b.area
    if ratio > max_size_ratio or ratio < 1.0 / max_size_ratio:
        return False
    if _iou(a, b) >= iou_match:
        return True
    return _center_dist(a, b) <= center_match_k * max(a.diag, b.diag)


@dataclass
class _Track:
    frames: list[int] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)
    last_frame: int = -1


def confirm_tracks(per_frame: Sequence[Sequence[Box]],
                   iou_match: float = DEFAULTS["iou_match"],
                   center_match_k: float = DEFAULTS["center_match_k"],
                   max_size_ratio: float = DEFAULTS["max_size_ratio"],
                   max_gap: int = DEFAULTS["max_gap"],
                   min_track_len: int = DEFAULTS["min_track_len"],
                   min_span: int = DEFAULTS["min_span"]) -> list[list[Box]]:
    """Return per-frame boxes with `confirmed=True` for persistent detections.

    Input is the C order: per frame, a list of hand boxes. Output keeps the same
    shape so a consumer can simply skip boxes where `confirmed` is False.
    """
    tracks: list[_Track] = []

    for f, boxes in enumerate(per_frame):
        assigned: set[int] = set()
        # Greedy: strongest association first, so a close match cannot be stolen
        # by a weaker neighbour.
        pairs = []
        for bi, box in enumerate(boxes):
            for ti, tr in enumerate(tracks):
                if f - tr.last_frame > max_gap + 1:
                    continue
                if f - tr.last_frame < 1:
                    continue
                if is_match(tr.boxes[-1], box, iou_match, center_match_k, max_size_ratio):
                    # prefer higher IoU, then smaller center distance
                    pairs.append((_iou(tr.boxes[-1], box), -_center_dist(tr.boxes[-1], box),
                                  bi, ti))
        pairs.sort(reverse=True)
        for _iou_v, _neg_d, bi, ti in pairs:
            if bi in assigned:
                continue
            if tracks[ti].last_frame == f:
                continue
            assigned.add(bi)
            tracks[ti].frames.append(f)
            tracks[ti].boxes.append(boxes[bi])
            tracks[ti].last_frame = f
        # unmatched detections start new tracks
        for bi, box in enumerate(boxes):
            if bi in assigned:
                continue
            tracks.append(_Track(frames=[f], boxes=[box], last_frame=f))

    out = [[Box(b.x, b.y, b.w, b.h, b.confidence, False) for b in boxes]
           for boxes in per_frame]
    for tr in tracks:
        span = tr.frames[-1] - tr.frames[0] + 1
        if len(tr.boxes) < min_track_len or span < min_span:
            continue
        for f, box in zip(tr.frames, tr.boxes):
            # mark by position, keeping the original per-frame order stable
            for cand in out[f]:
                if (cand.x == box.x and cand.y == box.y and cand.w == box.w
                        and cand.h == box.h):
                    cand.confirmed = True
                    break
    return out


def confirm_c_jsonl(records: Iterable[dict], **kwargs) -> list[dict]:
    """Apply confirmation to C JSONL records (list of per-frame dicts)."""
    records = list(records)
    per_frame = []
    for rec in records:
        boxes = []
        for h in rec.get("hands", []):
            bx = h.get("bbox") or [0, 0, 0, 0]
            boxes.append(Box(float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]),
                             float(h.get("confidence", 1.0))))
        per_frame.append(boxes)

    confirmed = confirm_tracks(per_frame, **kwargs)

    out = []
    for rec, boxes in zip(records, confirmed):
        new = dict(rec)
        new["hands"] = [b.as_dict() for b in boxes if b.confirmed]
        new["hands_confirmed_by"] = "temporal_hand_filter"
        new["hands_confirmed_n"] = len(new["hands"])
        new["hands_raw_n"] = len(boxes)
        out.append(new)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Temporal hand confirmation over C perception JSONL output.")
    ap.add_argument("--input", required=True, help="C JSONL (raw per-frame detections)")
    ap.add_argument("--output", required=True, help="write confirmed JSONL here")
    for key, val in DEFAULTS.items():
        ap.add_argument("--" + key.replace("_", "-"), type=type(val), default=val)
    args = ap.parse_args(argv)

    records = [json.loads(line) for line in open(args.input, encoding="utf-8")
               if line.strip()]
    kwargs = {k: getattr(args, k) for k in DEFAULTS}
    out = confirm_c_jsonl(records, **kwargs)
    with open(args.output, "w", encoding="utf-8") as fh:
        for rec in out:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    raw = sum(r["hands_raw_n"] for r in out)
    conf = sum(r["hands_confirmed_n"] for r in out)
    sys.stderr.write("temporal_hand_filter: %d frames, raw %d boxes -> confirmed %d\n"
                     % (len(out), raw, conf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
