#!/usr/bin/env python3
"""Extract the RKNN model-header metadata (attrs + quant_tab) from a .rknn file.

This is a read-only parser for the model container; it does not run inference.
The header is a Python-dict repr placed after the RKNN binary preamble.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def extract(path: Path) -> dict:
    data = path.read_bytes()
    start = data.find(b"{'attrs'")
    if start < 0:
        start = data.find(b'{"attrs"')
    if start < 0:
        raise SystemExit(f"no RKNN metadata header in {path}")
    depth = 0
    in_string = False
    escaped = False
    quote = ""
    end = -1
    for index in range(start, len(data)):
        byte = data[index:index + 1]
        char = byte.decode("latin-1")
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            continue
        if char in "'\"":
            in_string = True
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end < 0:
        raise SystemExit("unterminated RKNN metadata header")
    text = data[start:end].decode("utf-8", errors="strict")
    return ast.literal_eval(text)


def main() -> int:
    path = Path(sys.argv[1])
    meta = extract(path)
    attrs = meta.get("attrs", {})
    quant = meta.get("quant_tab", {})
    result = {
        "file": str(path),
        "size": path.stat().st_size,
        "num_outputs": sum(1 for v in attrs.values() if v.get("is_output")),
        "outputs": [],
        "input": None,
        "quantized_tensors": 0,
    }
    for name, attr in attrs.items():
        if not attr.get("is_output"):
            result["input"] = {"name": name, **attr}
            continue
        q = quant.get(name, {})
        result["outputs"].append({
            "name": name,
            "index": attr.get("idx"),
            "shape": attr.get("shape"),
            "layout": attr.get("layout"),
            "attr_dtype": attr.get("dtype"),
            "quant_dtype": q.get("dtype"),
            "qtype": q.get("qtype"),
            "qmethod": q.get("qmethod"),
            "scale": q.get("scale"),
            "zero_point": q.get("zero_point"),
            "min": q.get("min"),
            "max": q.get("max"),
        })
    for q in quant.values():
        if q.get("qtype") or q.get("scale") or q.get("zero_point"):
            result["quantized_tensors"] += 1
    result["sdk_version"] = meta.get("sdk_version")
    result["target_platform"] = meta.get("target_platform")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
