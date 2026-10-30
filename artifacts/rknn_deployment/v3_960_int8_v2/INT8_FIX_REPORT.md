# INT8 拆分输出 · 量化修复结果

日期：2026-10-30

## 1. 问题与修复

`output0` 把框坐标（0–960）和类别分数（0–1）拼成一个张量 → RKNN 单尺度量化 → 分数被压平
（上一轮实测 INT8 反量化后 max 956 / mean 162，检出为 0）。

**修复：改用 DFL 布局输出。** 模型已有两个"干净"的输出张量：
`onnx::Reshape_725`（DFL logits，64 通道）与 `onnx::Sigmoid_769`（类别 logits，3 通道）。
它们**不与框坐标共享量化尺度**，因此 INT8 可以正常量化。

## 2. 三条转换路线实测

| 路线 | 转换 | INT8 精度（509 张） | 结论 |
|---|---|---|---|
| 只保留拆分输出（删 output0） | ❌ RKNN 2.5.0 崩溃 | — | 不可用 |
| keep-all + `boxes`/`scores` | ✅ | hand F1 0.458 | 分数仍被压缩，差 |
| **keep-all + DFL/logits 解码** | ✅ | **hand F1 0.6043** | ✅ 采用 |

## 3. 精度（509 张固定 val，阈值 ball 0.20 / hand 0.25 / racket 0.25）

| 类别 | 指标 | FP32 ONNX | FP16 RKNN | **INT8 RKNN** | 门槛 |
|---|---|---:|---:|---:|---|
| Ball | P | 0.8226 | 0.8095 | 0.7833 | |
| Ball | **R** | 0.5100 | 0.5100 | **0.4700** | ≥0.49 ❌ |
| Ball | F1 | 0.6296 | 0.6258 | 0.5875 | |
| Ball | AP50 | 0.4921 | 0.4870 | 0.4308 | |
| Hand | P | 0.6913 | 0.6917 | 0.6726 | |
| Hand | R | 0.5580 | 0.5589 | 0.5486 | |
| Hand | **F1** | 0.6176 | 0.6182 | **0.6043** | ≥0.60 ✅ |
| Hand | AP50 | 0.5042 | 0.5068 | 0.4926 | |
| Racket | P | 0.7600 | 0.7644 | 0.7557 | |
| Racket | **R** | 0.7557 | 0.7557 | **0.7557** | ≥0.73 ✅ |
| Racket | F1 | 0.7578 | 0.7600 | 0.7557 | |
| Racket | AP50 | 0.6890 | 0.6910 | 0.6899 | |

**判定**：Hand / Racket 达标；**Ball Recall 0.470 < 0.49，差 2 个点 → INT8 暂不作为正式候选。**
FP16 与 FP32 差距 ≤1.3 点，**可直接作为交付件**。

## 4. 输出张量数值范围（模拟器实测）

| 张量 | FP16 | INT8 |
|---|---|---|
| dfl (64ch) | [−36.19, 35.34] | [−26.95, 28.03] |
| class logits (3ch) | [−52.53, 2.51] | [−42.11, 2.29] |

两者量级接近 → **量化健康**（对比上一轮 output0 的 max 956）。
逐张量的 scale/zero-point 需在板端用 `rknn_query(RKNN_QUERY_OUTPUT_ATTR)` 读取
（`cpp/rknn_v3_detect_dfl.cpp` 已打印 `type` 与 `qnt_type`），本轮模拟器未单独导出 scale。

## 5. 文件

| 文件 | 说明 |
|---|---|
| `rknn/v3_960_fp16_dfl_layout.rknn` | FP16，可直接交付 |
| `rknn/v3_960_int8_dfl_layout.rknn` | INT8，Ball Recall 差 2 点，**暂不交付** |
| `pingpong_v3_960_split_keepall.onnx` | 转换用（原 6 输出 + boxes/scores） |
| `pingpong_v3_960_split.onnx` / `_dfl.onnx` | 拆分实验件（仅评测） |
| `cpp/rknn_v3_detect_dfl.cpp` | C++ DFL 解码（`--layout dfl|split`） |
| `accuracy/*.json` | 300 张与 509 张的逐类结果 |

## 6. 下一步（把 Ball Recall 从 0.470 拉回 0.49+）

1. 校准集加球：把 ball_only/ball_racket 两桶从 60 提到 150（仍只用 train）；
2. 混合精度：把 DFL 分支保留 FP16、只量化 backbone（`rknn.config` 的 hybrid/层精度设置）；
3. 若仍不行，交付 FP16（与 FP32 差 ≤1.3 点，代价只是文件大 ~30%、NPU 略慢）。
