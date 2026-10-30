#!/usr/bin/env python3
"""Add split outputs to the V3 ONNX **without removing anything**.

Why: rknn-toolkit2 2.5.0 crashes in its own fusion rule (_p_seperate_conv_rs_split) whenever the
final Concat is removed, but the untouched 6-output graph converts fine. So instead of deleting
output0 we KEEP every original output and simply expose the two tensors we actually want:

    outputs = [output0, Reshape_725, Sigmoid_769, Conv_607, Conv_643, Conv_679, boxes, scores]

`boxes` = /model.22/Mul_2_output_0   [1,4,18900]  pixel-space xyxy
`scores` = /model.22/Sigmoid_output_0[1,3,18900]  sigmoid probabilities (0..1)

Keeping output0 changes nothing numerically; the runtime just ignores it. What matters is that
boxes and scores are now SEPARATE output tensors, so RKNN gives each its own quantisation scale
instead of sharing one dominated by the box coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib

import onnx
from onnx import TensorProto, ValueInfoProto, helper

EXTRA = [("/model.22/Mul_2_output_0", "boxes"), ("/model.22/Sigmoid_output_0", "scores")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="artifacts/handoff/AFH03_RK3576_V3_RKNN/"
                                    "pingpong_yolov8n_gray_3cls_v3_960_960.onnx")
    ap.add_argument("--out", default="artifacts/rknn_deployment/v3_960_split_output/"
                                    "pingpong_v3_960_split_keepall.onnx")
    args = ap.parse_args()

    src = onnx.load(args.src)
    m = onnx.ModelProto()
    m.CopyFrom(src)
    g = m.graph
    prod = {o: n for n in g.node for o in n.output}

    inf = onnx.shape_inference.infer_shapes(src, strict_mode=False)
    shapes = {vi.name: [d.dim_value for d in vi.type.tensor_type.shape.dim]
              for vi in list(inf.graph.value_info) + list(inf.graph.output)}
    existing = {o.name for o in g.output}

    for tensor, name in EXTRA:
        if tensor not in prod:
            raise SystemExit("missing producer for %s" % tensor)
        g.node.append(helper.make_node("Identity", [tensor], [name], name="expose_" + name))
        dims = shapes.get(tensor) or shapes.get(tensor, [])
        if not dims or dims[0] == 0:
            dims = [1] + list(dims[1:])
        vi = ValueInfoProto()
        vi.name = name
        vi.type.tensor_type.elem_type = TensorProto.FLOAT
        for d in dims:
            vi.type.tensor_type.shape.dim.add().dim_value = int(d)
        g.output.append(vi)
        print("added output %-8s <- %s  shape=%s" % (name, tensor, [int(d) for d in dims]))

    onnx.checker.check_model(m)
    dst = pathlib.Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(m, str(dst))
    print("wrote", dst, dst.stat().st_size, hashlib.sha256(dst.read_bytes()).hexdigest())
    print("original outputs kept:", len(existing), "-> total outputs:", len(g.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
