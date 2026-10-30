"""Turn the V3 3-class YOLOv8n into a real 2-class (ball, hand) model.

This is structural surgery, not a rename:
  * backbone (layers 0..9), SPPF and neck are copied verbatim
  * the box/DFL branch (cv2 + dfl) is class-independent and copied verbatim
  * the classification branch cv3 is rebuilt with 2 output channels and its weights are taken
    from V3's channels 0 (ball) and 1 (hand); the racket channel is dropped
  * nc / no / names are set to 2, so the head really emits 4*16 + 2 = 66 channels

The script prints the parameter counts and verifies that the final conv of every cv3 branch has
exactly 2 output channels, then writes a checkpoint that `YOLO(...)` can resume from.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys

import torch
import torch.nn as nn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="artifacts/runs/unified_3cls_v3b/weights/best.pt")
    ap.add_argument("--out", default="artifacts/runs/v9_init_2cls.pt")
    args = ap.parse_args()

    from ultralytics import YOLO
    y = YOLO(args.src)
    model = y.model.float()
    det = model.model[-1]
    print("source: nc=%s  no=%s" % (det.nc, det.no))
    assert int(det.nc) == 3, "expected a 3-class source model"

    cv3_new = copy.deepcopy(det.cv3)
    copied = []
    for i, seq in enumerate(cv3_new):
        old = seq[-1]
        assert isinstance(old, nn.Conv2d) and old.out_channels == 3, "unexpected cv3 tail"
        new = nn.Conv2d(old.in_channels, 2, old.kernel_size, old.stride, old.padding,
                        dilation=old.dilation, groups=old.groups, bias=old.bias is not None)
        with torch.no_grad():
            new.weight.copy_(old.weight[:2].clone())      # channel 0 = ball, 1 = hand
            if old.bias is not None:
                new.bias.copy_(old.bias[:2].clone())
        seq[-1] = new
        copied.append({"level": i, "in": old.in_channels, "out_before": 3, "out_after": 2})
    det.cv3 = cv3_new

    det.nc = 2
    det.no = det.nc + det.reg_max * 4
    det.names = {0: "ball", 1: "hand"}
    model.names = {0: "ball", 1: "hand"}
    model.yaml["nc"] = 2
    model.yaml["names"] = {0: "ball", 1: "hand"}

    n_all = sum(p.numel() for p in model.parameters())
    n_det = sum(p.numel() for p in det.parameters())
    info = {"source": args.src, "nc": int(det.nc), "no": int(det.no),
            "params_total": int(n_all), "params_detect_head": int(n_det),
            "cv3_branches": copied}
    print(json.dumps(info, indent=2))

    # structural self-check: every cv3 tail must output exactly 2 channels
    for i, seq in enumerate(det.cv3):
        out_ch = seq[-1].out_channels
        assert out_ch == 2, "cv3[%d] still has %d channels" % (i, out_ch)
    x = torch.zeros(1, 3, 960, 960)
    model.eval()
    with torch.no_grad():
        o = model(x)
    shape = tuple(o[0].shape) if isinstance(o, (tuple, list)) else tuple(o.shape)
    print("forward output shape:", shape)
    # in eval mode Detect emits [1, 4 + nc, N]; `no` (66) is the raw conv channel count
    assert shape[1] == 4 + int(det.nc), "expected 4+nc=%d channels, got %d" % (4 + det.nc, shape[1])
    assert shape[1] == 6, "a 2-class head must emit 6 channels (4 box + 2 class)"

    ckpt = {"model": model.half() if False else model,
            "epoch": -1, "best_fitness": None, "date": "", "version": "",
            "train_args": dict(y.ckpt.get("train_args", {}) or {}),
            "v9_surgery": info}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(ckpt, str(out))
    print("wrote", out, out.stat().st_size)

    # reload check: the saved file must come back as a 2-class model
    y2 = YOLO(str(out))
    d2 = y2.model.model[-1]
    print("reload check: nc=%s no=%s cv3 out=%s" % (d2.nc, d2.no, [s[-1].out_channels for s in d2.cv3]))
    assert int(d2.nc) == 2 and int(d2.no) == 66
    return 0


if __name__ == "__main__":
    sys.exit(main())
