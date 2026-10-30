#!/usr/bin/env python3
"""Split the V3 detection head so box and class-score leave the graph as SEPARATE tensors.

Why: the original ONNX concatenates pixel-space box coordinates (0..960) with sigmoid class
scores (0..1) into one tensor `output0 = [1,7,18900]`. RKNN quantises a tensor with a single
scale, so the coordinates dominate the range and the scores collapse - that is why the first
INT8 model returned max 956 / mean 162 and fired zero boxes.

Two layouts are produced here, both WITHOUT re-training and WITHOUT touching any weight:

  LAYOUT "split"  (recommended for INT8)
      boxes  : /model.22/Mul_2_output_0   [1,4,18900]  pixel xyxy in the 960 letterbox space
      scores : /model.22/Sigmoid_output_0 [1,3,18900]  sigmoid probabilities in 0..1
    DFL + dist2bbox stay inside the graph (they are provably identical to the original path,
    so there is nothing to get wrong in C++).

  LAYOUT "dfl"    (Rockchip model-zoo style, for C++ DFL decode)
      dfl    : onnx::Reshape_725         [1,64,18900]  DFL logits (4 sides x 16 bins)
      logits : onnx::Sigmoid_769         [1,3,18900]   PRE-sigmoid class logits
    The C++ side must run softmax(16) -> expectation -> dist2bbox itself.

Graph surgery only: outputs are re-pointed at tensors that already exist, so weights and all
arithmetic are untouched. The source ONNX is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib

import onnx
from onnx import ValueInfoProto, helper


def find_producer(graph):
    return {out: node for node in graph.node for out in node.output}


def clone_with_outputs(src: onnx.ModelProto, out_specs, drop_names):
    """Return a copy of `src` whose graph outputs are `out_specs` = [(tensor, new_name), ...]."""
    m = onnx.ModelProto()
    m.CopyFrom(src)
    g = m.graph
    prod = find_producer(g)
    # shapes for the tensors we expose
    shapes = {}
    inferred = onnx.shape_inference.infer_shapes(src, strict_mode=False)
    for vi in list(inferred.graph.value_info) + list(inferred.graph.output):
        shapes[vi.name] = [d.dim_value for d in vi.type.tensor_type.shape.dim]
    new_outputs = []
    for tensor, new_name in out_specs:
        if tensor not in prod:
            raise SystemExit("tensor %s has no producer" % tensor)
        dims = shapes.get(tensor)
        if not dims:
            raise SystemExit("cannot infer shape for %s" % tensor)
        # expose it under a clean name via Identity (RKNN folds Identity away)
        g.node.append(helper.make_node("Identity", [tensor], [new_name], name="rename_" + new_name))
        vi = ValueInfoProto()
        vi.name = new_name
        vi.type.tensor_type.elem_type = onnx.TensorProto.FLOAT
        for d in dims:
            vi.type.tensor_type.shape.dim.add().dim_value = int(d)
        new_outputs.append(vi)
    del g.output[:]
    g.output.extend(new_outputs)
    # drop the Concat node whose only purpose was to build the removed tensor
    keep = [n for n in g.node if not (n.op_type == "Concat" and any(o in drop_names for o in n.output))]
    del g.node[:]
    g.node.extend(keep)
    onnx.checker.check_model(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="artifacts/handoff/AFH03_RK3576_V3_RKNN/"
                                    "pingpong_yolov8n_gray_3cls_v3_960_960.onnx")
    ap.add_argument("--outdir", default="artifacts/rknn_deployment/v3_960_split_output")
    args = ap.parse_args()

    src_path = pathlib.Path(args.src)
    src = onnx.load(str(src_path))
    print("source:", src_path.name, src_path.stat().st_size,
          hashlib.sha256(src_path.read_bytes()).hexdigest())
    print("source outputs:", [(o.name, [d.dim_value for d in o.type.tensor_type.shape.dim])
                              for o in src.graph.output])

    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    specs = {
        "split": [("/model.22/Mul_2_output_0", "boxes"), ("/model.22/Sigmoid_output_0", "scores")],
        "dfl": [("onnx::Reshape_725", "dfl"), ("onnx::Sigmoid_769", "scores_logits")],
    }
    written = []
    for name, spec in specs.items():
        m = clone_with_outputs(src, spec, drop_names={"output0"})
        dst = outdir / ("pingpong_v3_960_%s.onnx" % name)
        onnx.save(m, str(dst))
        size = dst.stat().st_size
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        outs = [(o.name, [d.dim_value for d in o.type.tensor_type.shape.dim]) for o in m.graph.output]
        print("wrote %-40s %9d B sha256=%s" % (dst.name, size, sha))
        print("   outputs:", outs)
        written.append((dst.name, size, sha))
    (outdir / "SPLIT_OUTPUTS.txt").write_text(
        "\n".join("%s  %d B  %s" % w for w in written) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
