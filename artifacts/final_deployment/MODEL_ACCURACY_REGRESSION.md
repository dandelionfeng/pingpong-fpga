# MODEL_ACCURACY_REGRESSION — V3 509 张固定验证集

日期：2026-11-03
验证集：`pingpong_unified_3cls_v3/images/val`，509 张
GT：Ball 100 / Hand 1,172 / Racket 176
预处理：GRAY8 → Gray3 → letterbox 960、pad 114、INTER_LINEAR、/255
阈值：ball 0.20 / hand 0.25 / racket 0.25
NMS：类内 IoU 0.50，每类最多 60

## 1. 总表

| 类别 | 指标 | FP32 ONNX | FP16 RKNN 模拟器 | INT8 RKNN 模拟器 | **C++ flat DFL** |
|---|---|---:|---:|---:|---:|
| Ball | P | 0.8226 | 0.8095 | 0.7833 | **0.8226** |
| Ball | R | **0.5100** | **0.5100** | **0.4700** | **0.5100** |
| Ball | F1 | 0.6296 | 0.6258 | 0.5875 | **0.6296** |
| Ball | AP50 | — | 0.4870 | 0.4308 | **0.4870** |
| Hand | P | 0.6913 | 0.6917 | 0.6726 | **0.6913** |
| Hand | R | 0.5580 | 0.5589 | 0.5486 | **0.5580** |
| Hand | F1 | 0.6176 | **0.6182** | **0.6043** | **0.6176** |
| Hand | AP50 | — | 0.5068 | 0.4926 | **0.5063** |
| Racket | P | 0.7600 | 0.7644 | 0.7557 | **0.7600** |
| Racket | R | **0.7557** | **0.7557** | **0.7557** | **0.7557** |
| Racket | F1 | 0.7578 | 0.7600 | 0.7557 | **0.7578** |
| Racket | AP50 | — | 0.6910 | 0.6899 | **0.6914** |

- FP16/INT8 是 `rknn-toolkit2 2.5.0 simulator, target_platform=rk3588` 代理，不是 RK3576J 板端。
- **C++ flat DFL** 是实际编译的 `dfl_flat_decoder.hpp`，由 509 张 ONNX 的 DFL/logits 输入，经 ctypes 调用，不是 Python 重新实现。
- C++ 与 FP32 的 P/R/F1 逐位一致；Hand AP50 仅差 0.0005（浮点/ctypes 求和顺序），无系统性退化。

## 2. 验收线

| 类别 | 门槛 | FP16 | INT8 | C++ 解码 |
|---|---|---|---|---|
| Ball Recall | ≥ 0.49 | **0.5100 PASS** | **0.4700 FAIL** | **0.5100 PASS** |
| Hand F1 | ≥ 0.60 | **0.6182 PASS** | 0.6043 PASS | **0.6176 PASS** |
| Racket Recall | ≥ 0.73 | **0.7557 PASS** | 0.7557 PASS | **0.7557 PASS** |

**FP16 精度通过；INT8 Ball Recall 不达标，不作为默认正式交付。**

## 3. 逐框结果与数值误差

- 509 张的逐图检测框、类别、置信度：`evidence/cpp_flat_509.json` 的 `per_image`（509 项，288,179 B）。
- 单帧 C++ vs Python 对照（`evidence/cpp_vs_python_one_frame.log`）：

```text
score max diff = 5.96e-08
center diff    = 6.10e-05 px
wh diff        = 9.16e-05 px
```

- 没有系统性坐标偏移；差异来自 float32 运算顺序，远小于 1 px。
- 逐类匹配结果（C++ 509）：Ball TP 51 / FP 11 / FN 49；Hand 654/292/518；Racket 133/42/43。
- 原始 JSON：`evidence/cpp_flat_509.json`、`fp16_rknn_509.json`、`int8_rknn_509.json`、`fp32_onnx_509.json`。

## 4. 设计保护

- **V3 权重未改**；未重新训练；未替换 `.rknn`/`.onnx`。
- **BallTrack 仍是正式唯一球源**；8 输出适配只替换 RKNN 输出解析，不向 `result.balls` 写入 YOLO ball。
- **Hand** 仍走 V3 原始检测与后续测量；未改测量逻辑。
- **Racket 过滤** 仍在结果传递层，发生在 NPU → DFL → NMS 之后；模型仍保留第三类。
- 960×960 输入、GRAY8 接口、阈值配置均未改。

## 5. 限制

- FP16/INT8/C++ 509 都是 **PC/模拟器**，不是 AFH03 板端；板端精度仍 **BLOCKED**。
- 8 输出 C++ 适配的 **实际 RKNN 加载**需要 runtime ≥ 2.5.0 和板子；当前无板。
- C++ NMS 使用现有 `YoloDetector` 路径；本轮 509 的 NMS 在 Python 侧完成，未单独做 C++ NMS 数值对照。
