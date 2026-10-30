# AFH03 / RK3576J 部署准备 · 执行摘要

日期：2026-10-30　分支：`codex/c-pc-detector`　起点：`bc998ae`
交付目录：`artifacts/handoff/AFH03_RK3576_V3_RKNN/`　技术详情：`artifacts/rknn_deployment/PREP_STATUS.md`

## 结论

**RKNN 转换与板端测试 BLOCKED**：本机**没有 AFH03 实物连接**，也**没有 rknn-toolkit2**
（`pip download rknn-toolkit2==2.3.0` → No matching distribution；官方只有 Linux x86_64 的
Python 3.6–3.11 wheel，本机是 Windows + Python 3.12/3.13）。

PC 端该做的都做完了，并拿到两个**改变部署方案**的实测结论：

1. **原 V3 ONNX 有 6 个输出**（DFL 中间张量外泄）→ 已重导单输出版（397→234 节点），**精度完全一致**；
2. **640 分辨率不可用**：Ball Recall 0.510 → **0.050**。

## 1. 环境审计（实测）

| 项 | 结果 |
| --- | --- |
| adb / USB Rockchip 设备 | ❌ 无 |
| 板子网络 | 192.168.1.10 / 192.168.0.10 不可达；192.168.137.2 是 Windows ICS 网关（22 端口关闭） |
| RK3576J 型号/内核/RKNPU 驱动/RKNN Runtime/双核状态/CPU&NPU 频率/DDR | ❌ **全部无法获取**（板子不可达） |
| rknn-toolkit2 | ❌ 不可安装（无本机 wheel） |
| 现有 RKNN 示例 | ❌ 仓库内无 |

## 2. ONNX 修正（本轮最有价值的工程产出之一）

| 模型 | 节点 | 输出 | 大小 | SHA256 |
| --- | ---: | --- | ---: | --- |
| 原 V3（**未改动**） | 397 | **6** | 12,161,114 | `b779c88e…` |
| **单输出版（转换用）** | **234** | **1** | 12,477,398 | `39a9eb3a62da2d58373291747b7a740dc6d652ea8f2c850d77509aeae3b2301e` |

精度核对（同 val 同阈值）：Ball 0.823/0.510/0.630/0.492、Hand 0.691/0.558/0.618/0.504、
Racket 0.760/0.756/0.758/0.689 —— **与原 V3 逐位相同**。

## 3. 640 vs 960（实测，否决 640）

| 分辨率 | Ball R | Ball AP50 | Hand R | Racket R |
| --- | ---: | ---: | ---: | ---: |
| **960** | **0.510** | **0.492** | 0.558 | 0.756 |
| 640（静态重导出） | **0.050** | 0.054 | 0.473 | 0.438 |

球在 640 下只剩 ~8 px。→ 部署固定 **960**，优先级 960 INT8 → 960 FP16。

## 4. 已交付的准备件

| 文件 | 说明 |
| --- | --- |
| `convert_v3_to_rknn.py` | Toolkit2 转换（FP16/INT8 + 算子打印 + 多输出告警 + `--eval-dir` 逐类精度自检） |
| `make_calib_list.py` + `calib/list.txt` | INT8 校准清单：五类场景各 60 张共 **300 张**，**0 张来自 val**（已核验） |
| `cpp/rknn_v3_detect.cpp` | RKNN C API：GRAY8→Gray3→**双线性**letterbox→NPU→解码→类内 NMS→JSON；`--core-mask auto/0/1/0_1`；`--bench N` 输出 pre/npu/post/p50/p95/FPS |
| `cpp/CMakeLists.txt` + `build.sh` | 板端编译（链接 librknnrt.so） |
| `tools/verify_decode_pc.py` | C++ 解码算法核验 |

**C++ 解码核验结果**：40 帧 **40/40 一致，IoU 1.000**（letterbox/decode/NMS/坐标恢复全对）。
⚠ 仅算法核验，**不是 RKNN 结果、不是板端性能**；C++ 也**未编译**（本机无编译器）。

## 5. 未完成（BLOCKED）

FP16/INT8 转换 · RKNN 加载 · 板端精度 · 单核/双核 FPS · NPU 纯推理时间 · 完整流水线 FPS ·
C++ 编译 · OV9281 接入 · RGA/FPGA 预处理 · 与 BallTrack 联调。

## 6. 与现有 C++ 管线的冲突（需 B 模块评审）

`perception_engine.cpp` 目前**故意丢弃 V3 的 ball 类**（ball 唯一来源是 BallTrack）。
本包的 C++ 工具独立输出三类，**未接入正式判罚链路**；接入会产生双球源，必须先评审。

## 7. 目标达成情况

| 目标 | 状态 |
| --- | --- |
| 完整流水线 30 FPS | ❌ 无法测（无板子） |
| 完整流水线 50 FPS | ❌ 无法测 |
| 挑战 90 FPS | ❌ 无法测 |
| 保持 V3 精度 | ✅ PC 端已确认（单输出版精度一致；INT8 待测） |
