# MODEL_CARD — V3 Unified YOLOv8n（Ball + Hand 过滤版）

## 基本信息

| 项 | 值 |
|---|---|
| 名称 | V3 Unified YOLOv8n · 3-class detector，**出口过滤为 Ball + Hand** |
| 架构 | YOLOv8n，**三分类**检测头（ball / hand / racket），**未改动** |
| 交付格式 | RKNN **FP16** + 原始 ONNX |
| RKNN 文件 | `v3_960_fp16_dfl_layout.rknn`，**13,038,908 B** |
| RKNN SHA256 | `1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b` |
| ONNX 文件 | `pingpong_yolov8n_gray_3cls_v3_960_960.onnx`，**12,161,114 B** |
| ONNX SHA256 | `b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba` |
| 输入 | [1,3,960,960]，源码为 GRAY8 → Gray3 → letterbox 填充 114 → /255 |
| 输出（RKNN） | `dfl` [1,64,18900] + `scores_logits` [1,3,18900] |
| 类别 | 0=ball, 1=hand, **2=racket（模型仍计算，出口丢弃）** |
| 转换工具 | rknn-toolkit2 **2.5.0** |
| target_platform | rk3576 |
| 过滤配置 | `filter_config.yaml`：`keep: [0,1]`、`drop: [2]` |

## 关键澄清：这不是双分类模型

| 说法 | 事实 |
|---|---|
| "双分类模型" | ❌ **不是**。模型的分类头仍是 3 通道，仍计算 racket |
| "过滤掉 racket" | ✅ 是。解码 + NMS 之后丢弃 class 2 |
| "重新训练过" | ❌ 没有。权重一个字节未改 |
| "NPU 变快" | ❌ 不会。三类都要算完 |

**为什么不用 V9 那种真双分类**：V9 实验（真改结构 + 重训）已证明 Ball Recall 从 0.510
掉到 0.370，比过滤方案差得多。详见 `artifacts/unified_3cls_v9/`。

## 精度（509 张固定 val，CPU/ONNX 同权重）

| 类别 | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Ball | 51 | 11 | 49 | 0.8226 | 0.5100 | 0.6296 |
| Hand | 654 | 292 | 518 | 0.6913 | 0.5580 | 0.6176 |
| Racket | 过滤后 0 | — | — | — | — | — |

AP50：Ball 0.4921 / Hand 0.5042。阈值 ball 0.20、hand 0.25；比对 IoU 0.5、类内 NMS 0.5。

> PC/ONNX 评测，**非 AFH03 板端实测**。

## 性能（CPU 后处理，非 NPU）

| 阶段 | 耗时 |
|---|---:|
| 三类解码 + NMS | 1.747 ms |
| 类别过滤 | 0.0042 ms |

## 已知限制

1. **板端未验证**：无 AFH03 实物，NPU 精度与 FPS 均未测。
2. **C++ 未编译**：本机无编译器（需 aarch64 + `librknnrt.so`）。
3. **OV9281 未接入**：仅支持离线 GRAY8 帧（raw / pgm）。
4. **Ball 召回 0.510**：19–24 px 小球是长期瓶颈；V9 已证明删类无用。
5. **不能直接接判罚链路**：YOLO 的 ball 与 BallTrack 冲突，需 B 模块审核。
6. **验证集非独立测试集**：V2–V9 多轮使用过。
