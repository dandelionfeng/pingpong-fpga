# C 端感知 —— CAPTAIN INTEGRATION V2.2（960 hand）

> Supersedes `C_FINAL_HANDOFF_V2.md` 中的 hand 部分。**接口契约完全不变。**

日期：2026-10-17　分支：`codex/c-pc-detector`

## 1. 变更摘要

| 项 | V2.1 | **V2.2** |
| --- | --- | --- |
| hand 模型 | `hand_yolov8n_gray_interface_v1.onnx`（640，hand-keypoints 域） | **`hand_yolov8n_gray_final_v2_960.onnx`（960，BodyHands 域）** |
| hand 输入尺寸 | 640（全局） | **960（从该 ONNX 自己的 input shape 读取）** |
| racket 输入尺寸 | 640（全局） | **640（从它自己的 ONNX 读取，独立于 hand）** |
| ball / racket 权重 | —— | **完全未改** |
| 对外接口 | —— | **完全未改** |

## 2. C++ 输入尺寸修复

原实现用**单一全局 `Config::imgsz`** 同时控制 hand 与 racket。960 hand 模型在 640
张量下会被 ONNX Runtime 拒绝，而错误被吞掉后表现为"本帧没有手"——**静默失败**。

修复后：

1. `YoloDetector::load()` 读取**该模型自己**的 `inputShape()`，校验 4-D、
   `channels==3`、batch 为 1 或动态、H==W，据此得到 `imgsz_`；
2. `detect()` 每次推理前用 `validateInputAgainstModel()` 复核：模型声明尺寸、
   张量元素数、实际构造尺寸三者必须一致；
3. 任何不一致都会带明确错误码返回，并被引擎写进 `PerceptionResult::warnings`
   同时打到 stderr：
   `YOLO_INPUT_CONTRACT_MISMATCH` / `YOLO_TENSOR_SIZE_MISMATCH` /
   `YOLO_INFERENCE_FAILED` / `YOLO_OUTPUT_CONTRACT_MISMATCH`；
4. 配置里的 `imgsz` 键已移除，不再有全局尺寸。

单测 `testPerDetectorInputSize` 断言 hand=960、racket=640 且两者不相等。

## 3. hand 域内结果（BNDSTT_MANUAL_GT_V1，41 图 / 54 hand GT，conf 0.25）

| 指标 | V2.1（640） | **V2.2（960）** |
| --- | --- | --- |
| Precision | 0.3494 | **0.3626** |
| Recall | 0.5370 | **0.6111** |
| F1 | 0.4234 | **0.4552** |
| AP50 | 0.3376 | **0.3789** |
| TP/FP/FN | 29/54/25 | **33/58/21** |

对比最初 baseline（R=0.0000 / AP50=0.0000）：**Recall +0.6111，AP50 +0.3789**。

**checkpoint 选择方式**：960 模型是在 BodyHands val 上选出的 best（mAP50 0.823 /
mAP50-95 0.433），**没有用 BNDSTT 评测集挑 checkpoint**。中途某 checkpoint 的
BNDSTT AP50 曾更高（0.5183），但未被采用——那等于用测试集选模型。

## 4. Python / C++ hand parity（960）

同一段 40 帧视频、同一 960 预处理：

| 项 | 值 |
| --- | --- |
| C++ hand 框数 | 73 |
| Python hand 框数 | 73 |
| 数量不一致帧 | **0** |
| 匹配对数 | **73 / 73** |
| 坐标最大差异 | **0.000865 px** |
| 坐标中位差异 | 0.000433 px |
| 未匹配 | 0 |
| 判定 | **PASS** |

## 5. 端到端（解压后一键 demo）

`run_demo.ps1` 在 `C:\cap_v22` 解压目录实测 **exit 0**：

```
Done. frames=40  ball DETECTED=29 WARMUP=4 DROPOUT=7  hand boxes=73  racket boxes=28
mean inference 1893.51 ms/frame
```

- hand 框数 **0（V2.1）→ 73（V2.2）**
- ball 检出 29/40、racket 28 框 —— **与 V2.1 一致，未被影响**

## 6. 测试

| 项 | 结果 |
| --- | --- |
| `tools/check_repo.py` | 259 tracked files, 0 problems |
| `pytest tests -q` | **94 passed** |
| `unittest discover -s tests` | **30 OK** |
| C++ `c_actual_tests`（无模型） | **20/20 PASS** |
| C++ `c_actual_tests`（960+640 混合） | **24/24 PASS** |

## 7. 交付物

| 项 | 值 |
| --- | --- |
| 包 | `artifacts/handoff/C_PERCEPTION_CAPTAIN_INTEGRATION_V2_2.zip` |
| 大小 | 105,682,164 bytes（100.79 MB） |
| SHA256 | `b0329e9d1b8701884710d1ce0ecacd89af30d8a8e820799ec243e914705d36e5` |
| V2.1 | 保留未动（哈希校验一致） |

## 8. 非阻塞项

- CPU demo **非实时**：960 hand 比 640 更贵，40 帧平均约 1893 ms/帧（V2.1 约 663 ms）。
- RKNN 未转换、无真机验证。
- hand 的 BodyHands 许可仍未明确（项目页声明版权归作者）。
- `hand_conf` 保持 0.25，**未用评测集调阈值**。
