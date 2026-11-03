# BOARD_ACCURACY_REPORT — AFH03 / RK3576J

日期：2026-11-03

## 1. 结论

| 项 | 状态 |
|---|---|
| 板端 C++ 509 张 | **NOT TESTED（无板）** |
| FP32 ONNX 509 张 | **PASS（PC）** |
| FP16 RKNN 509 张 | **PASS（模拟器代理）** |
| C++ flat DFL 509 张 | **PASS（PC 主机）** |
| INT8 509 张 | **FAIL（Ball R 0.470）** |
| Ball Recall ≥0.49 | FP16/C++ **PASS**；INT8 **FAIL** |
| Hand F1 ≥0.60 | FP16/C++ **PASS** |
| Racket Recall ≥0.73 | **PASS（过滤前）** |

## 2. 参考结果（来自第二阶段实际执行）

| 类别 | 指标 | FP32 ONNX | FP16 RKNN | C++ flat DFL |
|---|---|---:|---:|---:|
| Ball | P/R/F1 | .8226/.5100/.6296 | .8095/.5100/.6258 | .8226/.5100/.6296 |
| Hand | P/R/F1 | .6913/.5580/.6176 | .6917/.5589/.6182 | .6913/.5580/.6176 |
| Racket | P/R/F1 | .7600/.7557/.7578 | .7644/.7557/.7600 | .7600/.7557/.7578 |

C++ 509 逐图结果：`../final_deployment/evidence/cpp_flat_509.json`（509 项），单帧误差 score 5.96e-08、中心/宽高 9.16e-05 px。

## 3. 板端验收（待执行）

在 AFH03 上：

1. 用 2.5.0 runtime 加载 FP16 模型；
2. 对 509 张固定 val 逐帧运行正式 C++ 推理；
3. 保存逐框 JSON（class/confidence/bbox）；
4. 用同一匹配规则（类内一对一，IoU≥0.5；ball .20 / hand .25 / racket .25；NMS .50）计算。

验收线：

```text
Ball Recall >= 0.49
Hand F1 >= 0.60
Racket Recall >= 0.73（过滤前）
```

若 Ball 低于 0.49：先查 letterbox 114、是否重复 /255、模型 SHA、runtime 2.5.0、输入 GRAY8/Gray3；不要降低阈值掩盖漏检。

## 4. 设计保护

- BallTrack 仍是正式链路唯一球源；未把 YOLO Ball 写入 `result.balls`；
- Hand 检测/测量逻辑未改；
- Racket 在结果传递层过滤（NPU→DFL→NMS 之后）；
- 960×960、V3 权重、GRAY8 接口未改。

## 5. 状态

**板端精度：BLOCKED（无 AFH03 实物）。** 现有 PC/模拟器/C++ 主机结果不能写成板端 509 通过。
