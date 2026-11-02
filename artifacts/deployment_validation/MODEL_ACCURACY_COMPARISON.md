# MODEL_ACCURACY_COMPARISON — V3 三分类

日期：2026-11-03
固定验证集：`pingpong_unified_3cls_v3` 的 509 张 val（Ball 100 / Hand 1,172 / Racket 176 GT）。
预处理：GRAY8 → Gray3 → letterbox 960、pad 114、INTER_LINEAR、/255。
匹配：类内一对一贪心，IoU ≥ 0.5；阈值 ball 0.20 / hand 0.25 / racket 0.25；NMS 0.5。

## 1. 实际执行结果

| 类别 | 指标 | FP32 ONNX | FP16 RKNN | INT8 RKNN | FP16−FP32 | INT8−FP32 |
|---|---|---:|---:|---:|---:|---:|
| Ball | Precision | 0.8226 | 0.8095 | 0.7833 | −0.0131 | −0.0393 |
| Ball | Recall | **0.5100** | **0.5100** | **0.4700** | 0.0000 | **−0.0400** |
| Ball | F1 | 0.6296 | 0.6258 | 0.5875 | −0.0038 | −0.0421 |
| Hand | Precision | 0.6913 | 0.6917 | 0.6726 | +0.0004 | −0.0187 |
| Hand | Recall | 0.5580 | 0.5589 | 0.5486 | +0.0009 | −0.0094 |
| Hand | F1 | 0.6176 | **0.6182** | **0.6043** | +0.0006 | −0.0133 |
| Racket | Precision | 0.7600 | 0.7644 | 0.7557 | +0.0044 | −0.0043 |
| Racket | Recall | **0.7557** | **0.7557** | **0.7557** | 0.0000 | 0.0000 |
| Racket | F1 | 0.7578 | 0.7600 | 0.7557 | +0.0022 | −0.0021 |

FP16/INT8 均为 **rknn-toolkit2 2.5.0 simulator, target_platform=rk3588 代理**；不是 RK3576J 板端。FP32 是 ONNX Runtime CPU 实际执行。

原始文件：

- `evidence/fp32_onnx_509.json`
- `evidence/fp16_rknn_509.json`
- `evidence/int8_rknn_509.json`

## 2. 验收线

| 类别 | 门槛 | FP16 | INT8 |
|---|---|---|---|
| Ball Recall | ≥ 0.49 | **0.5100 PASS** | **0.4700 FAIL** |
| Hand F1 | ≥ 0.60 | **0.6182 PASS** | **0.6043 PASS** |
| Racket Recall | ≥ 0.73 | **0.7557 PASS** | **0.7557 PASS** |

**FP16 可以作为精度候选正式部署件；INT8 不可作为正式部署件**（Ball 召回差 2 点）。优先 FP16 混合精度/FP16 交付。

## 3. 设计保护

- Ball 仍唯一来源 BallTrack；没有启用 YOLO ball 作为正式球源。
- Hand 测量逻辑未改。
- Racket 正式链路过滤策略未改（Racket 过滤是 **INTENTIONAL_DESIGN**，不是 BUG）。
- 960×960 输入、GRAY8 相机接口、V3 三分类权重均未改。
- 未修改任何 `.rknn`、`.onnx`、模型配置中的 `.005`/最终阈值。

## 4. 结论

- **FP16 精度：PASS（模拟器代理）**；实际板端精度仍 **BLOCKED**。
- **INT8：FAIL**，不应为了 FPS 牺牲 Ball 召回。
- 生产 runtime 与模型契约另有 **FAIL**（8 输出 vs 1/6），见 `QUANTIZATION_VALIDATION.md`；因此即使 FP16 精度达标，也不能直接判定“可交付队长”。
