import ctypes
import pathlib
import sys

import cv2
import numpy as np
import onnxruntime as ort

sys.path.insert(0, "/mnt/d/pp_fix_work/artifacts/deployment_validation/tools")
# copy of Python reference decode, independent of ctypes
from eval_onnx_dfl import letterbox, decode, SIZE, PAD

onnx = sys.argv[1]
image = sys.argv[2]
lib = ctypes.CDLL("/tmp/libflat_decode.so")
fp = ctypes.POINTER(ctypes.c_float)
lib.c_flat_decode.argtypes = [fp, fp, fp, ctypes.c_int, ctypes.c_float, ctypes.c_int]
lib.c_flat_decode.restype = ctypes.c_int
sess = ort.InferenceSession(onnx, providers=["CPUExecutionProvider"])
g = cv2.imdecode(np.fromfile(image, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
h, w = g.shape[:2]
x, s, px, py = letterbox(g)
outs = sess.run(None, {sess.get_inputs()[0].name: np.transpose(x, (0, 3, 1, 2)).astype(np.float32) / 255.0})
dfl = logits = None
for a in outs:
    v = a[0] if a.ndim == 3 else a
    if v.ndim == 2 and v.shape[0] == 64 and dfl is None:
        dfl = v
    elif v.ndim == 2 and v.shape[0] == 3 and logits is None:
        logits = v
print("shapes", dfl.shape, logits.shape, "dfl range", dfl.min(), dfl.max(), "logits", logits.min(), logits.max())
anchors = dfl.shape[1]
out = np.zeros((7, anchors), np.float32)
rc = lib.c_flat_decode(np.ascontiguousarray(dfl, np.float32).ctypes.data_as(fp),
                       np.ascontiguousarray(logits, np.float32).ctypes.data_as(fp),
                       out.ctypes.data_as(fp), anchors, -1.0, 0)
print("rc", rc, "out range", out.min(), out.max())
print("cpp first cols", out[:, :4])
dets = decode(dfl, logits, s, px, py, w, h)
print("py dets", dets[:5])
print("scores max", out[4:].max(), "argmax", out[4:].argmax())
# compare C++ scores to Python sigmoid
sc = 1.0 / (1.0 + np.exp(-logits))
print("score max diff", np.abs(out[4:] - sc).max())
# compare boxes in 960 space
py_x = np.zeros((4, anchors), np.float32)
d = dfl.reshape(4, 16, -1)
d = d - d.max(axis=1, keepdims=True)
e = np.exp(d); p = e / e.sum(axis=1, keepdims=True)
dist = (p * np.arange(16, dtype=np.float32).reshape(1, 16, 1)).sum(axis=1)
strides = np.concatenate([np.full(120*120,8), np.full(60*60,16), np.full(30*30,32)]).astype(np.float32)
gx = np.concatenate([np.tile(np.arange(120),120), np.tile(np.arange(60),60), np.tile(np.arange(30),30)]).astype(np.float32)
gy = np.concatenate([np.repeat(np.arange(120),120), np.repeat(np.arange(60),60), np.repeat(np.arange(30),30)]).astype(np.float32)
ax=(gx+.5)*strides; ay=(gy+.5)*strides
print("center diff", np.abs(out[0] - (ax+(dist[2]-dist[0])*0.5*strides)).max(), np.abs(out[1] - (ay+(dist[3]-dist[1])*0.5*strides)).max())
print("wh diff", np.abs(out[2] - (dist[0]+dist[2])*strides).max(), np.abs(out[3] - (dist[1]+dist[3])*strides).max())
