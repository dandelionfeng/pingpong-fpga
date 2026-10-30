# DEPLOYMENT_STATUS — 部署状态（诚实清单）

日期：2026-10-30　版本：V3 Ball + Hand Filtered　提交：`08b5fe0`

## ✅ 已完成并有实测证据

| 项 | 证据 |
|---|---|
| 模型文件真实存在 | RKNN 13,038,908 B，sha256 `1bcff6ff…cad0b` |
| ONNX 原始未改 | 12,161,114 B，sha256 `b779c88e…254ba` |
| 类别过滤已实现 | `cpp/rknn_v3_detect_filtered.cpp`（解码+NMS 之后过滤） |
| **509 帧逐项等价** | Ball/Hand 的 TP/FP/FN/P/R/F1/AP50 **完全一致**；**509/509 帧**被保留检测逐项相同 |
| Racket 已归零 | 过滤前 175 个 → 过滤后 **0** |
| 后处理耗时已测 | 解码+NMS 1.747 ms；过滤 0.0042 ms（CPU） |
| 配置文件 | `filter_config.yaml`（keep [0,1], drop [2]） |

## ❌ 未验证（BLOCKED，不得宣称）

| 项 | 状态 | 原因 |
|---|---|---|
| **AFH03 板端运行** | ❌ 未做 | 无实物；无 adb/USB 设备 |
| **板端精度** | ❌ 未测 | 同上 |
| **NPU FPS（单核/双核）** | ❌ 未测 | 同上 |
| **NPU 纯推理延迟 / P50 / P95** | ❌ 未测 | 同上 |
| **完整流水线 FPS** | ❌ 未测 | 同上（且本包不含相机采集） |
| **C++ 真实编译** | ❌ 未做 | 本机无 cmake/g++；需板端 aarch64 + `librknnrt.so` |
| **OV9281 接入** | ❌ 未做 | 无相机 |
| **RGA/FPGA 预处理** | ❌ 未做 | 仅方案 |
| **接入正式判罚链路** | ❌ 未做 | 需 B 模块审核（YOLO ball 与 BallTrack 双源冲突） |

## ⚠ 三条必须遵守的约束

1. **Racket 过滤 ≠ 模型不计算 Racket**。NPU 仍算三类，过滤只发生在出口。
2. **类别过滤不会提升 NPU 速度**。它只减少后处理与下游传递。
3. **本工具输出的 YOLO Ball 不得直接接入 `result.balls`**。
   现有 `perception_engine.cpp:210-224` 刻意丢弃 YOLO ball，BallTrack 是唯一球源；
   改动必须经 B 模块技术复核 + 蒲公英批准。

## 板端待办（拿到 AFH03 后按序）

1. 确认 `librknnrt.so` 版本 ≥ 2.5.0；
2. `cd cpp && ./build.sh`（老 SDK 加 `-DUSE_CORE_MASK=OFF`）；
3. 单帧自检：`--input frame.raw --width 1920 --height 1080 --classes 0,1`；
4. 检查输出里 `filtered_out > 0` 且 `detections` 中**没有 racket**；
5. 500 帧基准：`--bench 500` 分别跑 `auto / 0 / 1 / 0_1`；
6. 509 帧板端精度复测（口径见 `EVALUATION_REPORT.md`）。

## 一句话

**过滤这一环是真做完并且逐帧验证过的；板端那一环一点都没做。**
