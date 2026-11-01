#!/usr/bin/env python3
"""Generate the RKNN adapter sources from the reviewed C actual sources.

This script is intentionally path-independent: every input is resolved from
this file's location (or an explicit --source), never from the current working
directory. It fails loudly with the exact missing path instead of silently
generating an incomplete adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

THIS_FILE = Path(__file__).resolve()
NATIVE_ROOT = THIS_FILE.parents[2]          # source/native
DEFAULT_SOURCE = NATIVE_ROOT / "base/software/pc_pipeline/modules/c_actual"
DEFAULT_TENSOR = NATIVE_ROOT / "rk_runtime/c_rknn/image_tensor.inc"

REQUIRED_SOURCE_FILES = (
    "src/perception_engine.cpp",
    "src/balltrack_onnx.cpp",
    "src/preprocessing.cpp",
    "src/postprocessing.cpp",
    "src/yolo_detector_onnx.cpp",
    "src/detector_backend_c_actual.cpp",
    "src/internal_onnx.hpp",
    "src/specialist_detector.hpp",
)


class PrepareError(RuntimeError):
    """A required input/output path is missing or unusable."""


def require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise PrepareError(f"{label} not found: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_dir():
        raise PrepareError(f"{label} not found or not a directory: {path}")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_exact(source: Path, target: Path) -> None:
    target.write_bytes(source.read_bytes())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"C actual module directory (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument("--output", type=Path, required=True, help="generated source directory")
    args = parser.parse_args(argv)

    source = require_dir(args.source, "C actual source directory")
    output = args.output.resolve()
    if output.exists() and not output.is_dir():
        raise PrepareError(f"output path exists but is not a directory: {output}")

    for relative in REQUIRED_SOURCE_FILES:
        require_file(source / relative, f"required source file ({relative})")
    tensor_file = require_file(DEFAULT_TENSOR, "RKNN image tensor include")
    output.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, str]] = []

    for name in ("perception_engine.cpp", "balltrack_onnx.cpp", "preprocessing.cpp", "postprocessing.cpp"):
        src = require_file(source / "src" / name, f"required source file ({name})")
        copy_exact(src, output / name)
        records.append({"source": str(src), "sha256": sha256(src), "operation": "byte_exact_copy"})

    internal = require_file(source / "src/internal_onnx.hpp", "internal_onnx.hpp")
    header = internal.read_text(encoding="utf-8")
    if "#include <onnxruntime_cxx_api.h>" not in header:
        raise PrepareError(f"expected ONNX include not found in {internal}")
    header = header.replace("#include <onnxruntime_cxx_api.h>", '#include "runtime_session.hpp"')
    try:
        begin = header.index("class OrtSession {")
        end = header.index("// NCHW float tensor", begin)
    except ValueError as exc:
        raise PrepareError(f"internal_onnx.hpp structure changed; cannot locate OrtSession block: {internal}") from exc
    header = header[:begin] + header[end:]
    (output / "internal_onnx.hpp").write_text(header, encoding="utf-8")
    records.append({"source": str(internal), "sha256": sha256(internal),
                    "operation": "replace_internal_session"})

    yolo = require_file(source / "src/yolo_detector_onnx.cpp", "yolo_detector_onnx.cpp")
    yolo_text = yolo.read_text(encoding="utf-8")
    try:
        prefix_end = yolo_text.index("// ------------------------------------------------------------------ session")
        helpers_start = yolo_text.index("// ------------------------------------------------------------------ helpers")
    except ValueError as exc:
        raise PrepareError(f"yolo_detector_onnx.cpp structure changed: {yolo}") from exc
    prefix = yolo_text[:prefix_end]
    helpers = yolo_text[helpers_start:]
    try:
        image_begin = helpers.index("std::vector<float> imageToNchw(")
        image_end = helpers.index("// ------------------------------------------------------------- YOLO detector", image_begin)
    except ValueError as exc:
        raise PrepareError(f"imageToNchw block not found in {yolo}") from exc
    helpers = helpers[:image_begin] + tensor_file.read_text(encoding="utf-8") + helpers[image_end:]
    (output / "yolo_detector.cpp").write_text(prefix + helpers, encoding="utf-8")
    records.append({"source": str(yolo), "sha256": sha256(yolo),
                    "operation": "replace_internal_session_or_add_runtime_provenance"})

    bridge = require_file(source / "src/detector_backend_c_actual.cpp", "detector_backend_c_actual.cpp")
    bridge_text = bridge.read_text(encoding="utf-8")
    bridge_text = bridge_text.replace(
        '#include "c_perception_engine.hpp"',
        '#include "c_perception_engine.hpp"\n#include "runtime_session.hpp"',
        1,
    )
    needle = "    auto p = window && !all_ ?"
    if bridge_text.count(needle) != 1:
        raise PrepareError(f"unexpected bridge structure (missing inference branch): {bridge}")
    bridge_text = bridge_text.replace(
        needle,
        "    c_actual::resetRuntimeTimings();\n" + needle,
        1,
    )
    bridge_text = bridge_text.replace(
        'r.diagnostics["inference_backend"] = "onnxruntime";',
        'r.diagnostics["inference_backend"] = "rknn-runtime";',
        1,
    )
    needle = "    if (!all_ && p.ball.state == c_actual::BallState::kInvalid) {"
    if bridge_text.count(needle) != 1:
        raise PrepareError(f"unexpected bridge structure (missing ball state branch): {bridge}")
    bridge_text = bridge_text.replace(
        needle,
        '    r.diagnostics["inference_runtime"] = "rk3576-rknn-npu";\n'
        '    r.diagnostics["rknn_graph_ms"] = c_actual::lastRuntimeTimings();\n' + needle,
        1,
    )
    (output / "detector_backend_c_actual.cpp").write_text(bridge_text, encoding="utf-8")
    records.append({"source": str(bridge), "sha256": sha256(bridge),
                    "operation": "replace_internal_session_or_add_runtime_provenance"})

    specialist = require_file(source / "src/specialist_detector.hpp", "specialist_detector.hpp")
    copy_exact(specialist, output / "specialist_detector.hpp")
    records.append({"source": str(specialist), "sha256": sha256(specialist),
                    "operation": "byte_exact_copy_audit_only"})

    (output / "source-map.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("C_RKNN_ADAPTER_PREPARED")
    print(f"source={source}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PrepareError as exc:
        print(f"PREPARE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except OSError as exc:
        print(f"PREPARE_FAILED: filesystem error: {exc}", file=sys.stderr)
        raise SystemExit(2)
