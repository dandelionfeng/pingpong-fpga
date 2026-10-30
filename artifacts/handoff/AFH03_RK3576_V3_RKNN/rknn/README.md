# RKNN 已产出文件（WSL2 实测）

| 文件 | 大小 | 状态 | 说明 |
|---|---:|---|---|
| `v3_960_fp16_rk3576.rknn` | 13,025,519 B | ✅ 可试加载 | 由**原始 6 输出 ONNX** 转换，`target_platform=rk3576` |
| `v3_960_int8_rk3576_BROKEN_concat_quant.rknn` | 9,847,626 B | ❌ **不要用** | 输出被单尺度量化破坏，检出为 0；仅作证据 |
| `fp16_sim_accuracy_300imgs.json` | 664 B | 记录 | FP16 在模拟器上的逐类精度 |

## FP16 模拟器精度（300 张 val，全部为 vbh 手部图，rk3588 代理配置）

Hand：P 0.681 / R 0.546 / F1 0.606 / AP50 0.496（PC 端 FP32 全 509 张为 0.691/0.558/0.618/0.504）

**这是模拟器 + 代理平台，不是板端结果。**

## 复现

```bash
python3 - <<'PY'
from rknn.api import RKNN
r = RKNN(verbose=False)
r.config(target_platform='rk3576', mean_values=[[0,0,0]], std_values=[[255,255,255]], optimization_level=3)
assert r.load_onnx(model='pingpong_yolov8n_gray_3cls_v3_960_960.onnx') == 0   # 6 输出！
assert r.build(do_quantization=False) == 0
r.export_rknn('v3_960_fp16_rk3576.rknn')
PY
```

详细说明见 `CONVERSION_RESULTS.md`。
