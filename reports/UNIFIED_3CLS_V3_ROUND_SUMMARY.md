# 统一三分类 V3 · 本轮执行摘要

日期：2026-10-25　分支：`codex/c-pc-detector`　起点：`4f9c1ea`
交付：`artifacts/handoff/UNIFIED_3CLS_V3_FOR_CAPTAIN.zip`

## 结论

**V3 训练完成，Ball 与 Racket 在部署阈值下的 F1 分别 +5.7 / +4.4 个点，Hand 基本持平；
Ball Recall 仍是短板（0.460）。V2 保留为默认交付，V3 作为新的实验候选并行提供。**

## 1. 数据改造（本轮核心工作）

| 项 | V2 | **V3（V4 数据集）** |
| --- | --- | --- |
| train 图 | 3,910 | **4,431**（+521 张 BNDSTT 真实域球帧） |
| ball 框 | 1,978 | **2,499（+26.3%）** |
| hand 框 | 3,123 | 3,698（+575 自动候选，待人工复核） |
| racket 框 | 4,790 | 4,790（**未增加**） |
| val | 509 图 | **同一 509 图**（对比公平） |

- 新增的 521 帧此前**从未**被任何三分类模型使用，且属于**部署域（球馆发球）**。
- hand 候选由已验证的 hand 专项模型（`hand_v3_960`，conf≥0.45）生成，manifest 标记
  `AUTO_ASSISTED_HAND_CANDIDATE`，**不是人工标注**。
- racket 在该域自动补标注不可靠，**没有补**（避免注入噪声）。

## 2. 标注完整性

详见 `UNIFIED_V3_LABEL_AUDIT.md`。已修复：部署域无球数据（+521 帧）。部分修复：新增帧的 hand
（+575 候选，待复核）。**未修复**：新增帧的 racket、tabletennis 宽视角的 hand、hand 近景集的球/拍。

## 3. 训练

| 项 | 值 |
| --- | --- |
| 模型 | YOLOv8n，3 类，imgsz 960，batch 12 |
| 初始化 | `pingpong_3cls_v1/best.pt`（3 类兼容） |
| 实际轮数 | **15 / 16**（early stop） |
| 最佳 epoch | **9**（mAP50 0.6258 / mAP50-95 0.2621） |
| 耗时 | **0.533 h ≈ 32 分钟**，RTX 4060 Laptop 8.6 GB |
| 超参 | AdamW 3e-4，cos_lr，mosaic 0.2，scale 0.4，degrees 5，seed 42 |

> 另试过一次"从 V2 续训"：9 轮早停，ball R 0.440 / racket R 0.665，**更差**（已淘汰，
> 权重保留在 `artifacts/runs/unified_3cls_v3`）。这与前几轮观察一致——从已收敛权重重启
> 学习率调度会破坏最优点。

## 4. 评测（val 509 图，非独立测试集）

| 类别 | AP50 V2 → V3 | F1@0.25 V2 → V3 | Recall V2 → V3 |
| --- | --- | --- | --- |
| Ball | 0.519 → **0.538** | 0.561 → **0.618** | 0.475 → 0.460 |
| Hand | 0.613 → 0.607 | 0.626 → 0.618 | 0.557 → 0.538 |
| Racket | 0.735 → **0.738** | 0.714 → **0.758** | 0.679 → **0.727** |
| Overall | 0.623 → **0.627** | — | 0.571 → 0.575 |

明细与 TP/FP/FN 见 `UNIFIED_V3_COMPARISON.md`。

## 5. 导出与验证

| 项 | 值 |
| --- | --- |
| ONNX | `artifacts/files/models/unified_3cls_v3b/pingpong_yolov8n_gray_3cls_v3_960_960.onnx` |
| 大小 / SHA256 | 12,161,114 B / `b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba` |
| 权重 | `artifacts/runs/unified_3cls_v3b/weights/best.pt`（35e72c11…） |
| 输入 / 输出 | `[1,3,960,960]` → `[1,7,18900]`，类别 `0=ball,1=hand,2=racket` |
| PT/ONNX parity | ✅ raw 2.11e-03（float32 噪声）、sigmoid 4.17e-07、top-1 6/6 |
| 三类检出 | ✅ 10 张样例 → ball 4 / hand 11 / racket 9 |
| 延迟 | 74.0 ms/帧（CPU 4 线程；V2 70.4 ms） |
| ZIP | `UNIFIED_3CLS_V3_FOR_CAPTAIN.zip`，11,451,043 B，`e5730b06…`（解压复验通过） |

## 6. 未做（如实）

- 无独立测试集；无 OV9281 真实域验证；RKNN/NPU 未做；板端未跑；C++ 引擎未实测。
- 未尝试 YOLOv8s：现有证据（train/val 分类损失差距大）指向域偏移而非容量瓶颈。
- 未覆盖 V2 模型与 V2 交付包（哈希已核对未变）。
