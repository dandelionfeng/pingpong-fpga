"""Reuse the delivered C algorithms, replacing only the internal graph session."""
import argparse
import hashlib
import json
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
records=[]
for name in ('perception_engine.cpp','balltrack_onnx.cpp','preprocessing.cpp','postprocessing.cpp'):
    source=args.source/'src'/name
    raw=source.read_bytes()
    (args.output/name).write_bytes(raw)
    records.append(dict(source=str(source),sha256=hashlib.sha256(raw).hexdigest(),operation='byte_exact_copy'))
header=(args.source/'src/internal_onnx.hpp').read_text(encoding='utf-8')
header=header.replace('#include <onnxruntime_cxx_api.h>','#include "runtime_session.hpp"')
begin=header.index('class OrtSession {')
end=header.index('// NCHW float tensor',begin)
header=header[:begin]+header[end:]
(args.output/'internal_onnx.hpp').write_text(header,encoding='utf-8')
yolo=(args.source/'src/yolo_detector_onnx.cpp').read_text(encoding='utf-8')
prefix=yolo[:yolo.index('// ------------------------------------------------------------------ session')]
helpers=yolo[yolo.index('// ------------------------------------------------------------------ helpers'):]
begin=helpers.index('std::vector<float> imageToNchw(')
end=helpers.index('// ------------------------------------------------------------- YOLO detector',begin)
tensor=(Path(__file__).resolve().parents[2]/'software/rk_runtime/c_rknn/image_tensor.inc').read_text()
helpers=helpers[:begin]+tensor+helpers[end:]
(args.output/'yolo_detector.cpp').write_text(prefix+helpers,encoding='utf-8')
bridge=(args.source/'src/detector_backend_c_actual.cpp').read_text(encoding='utf-8')
bridge=bridge.replace('#include "c_perception_engine.hpp"','#include "c_perception_engine.hpp"\n#include "runtime_session.hpp"')
needle='    auto p = window && !all_ ?'
assert bridge.count(needle)==1
bridge=bridge.replace(needle,'    c_actual::resetRuntimeTimings();\n'+needle)
needle='    if (!all_ && p.ball.state == c_actual::BallState::kInvalid) {'
assert bridge.count(needle)==1
bridge=bridge.replace(needle,'    r.diagnostics["inference_runtime"] = "rk3576-rknn-npu";\n'
    '    r.diagnostics["rknn_graph_ms"] = c_actual::lastRuntimeTimings();\n'+needle)
(args.output/'detector_backend_c_actual.cpp').write_text(bridge,encoding='utf-8')
for name in ('internal_onnx.hpp','yolo_detector_onnx.cpp','detector_backend_c_actual.cpp'):
    p=args.source/'src'/name
    records.append(dict(source=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                        operation='replace_internal_session_or_add_runtime_provenance'))
(args.output/'source-map.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
print('C_RKNN_ADAPTER_PREPARED')

# The optional specialist audit mode uses the same replaced RKNN session API.
import shutil
shutil.copy2(args.source/'src/specialist_detector.hpp',args.output/'specialist_detector.hpp')
