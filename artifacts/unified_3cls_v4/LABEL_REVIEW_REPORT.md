# LABEL_REVIEW_REPORT — 521 张新增球帧的 Racket / Hand 标签审核

日期：2026-10-25　对象：`pingpong_unified_3cls_v4` 中新增的 521 张 BNDSTT 球帧（`ps_*`）

## 1. 方法

用**现成的 Racket 专项模型**（`racket_gray_onxx_tmp/racket_yolov8n_gray.onnx`，2 类，
只取 racket class）对这 521 帧逐帧推理，按最高 racket 分数分桶：

| 桶 | 判据 | 帧数 |
| --- | --- | ---: |
| **CONFIRMED_CANDIDATE** | top ≥ 0.40 | **104** |
| NEEDS_REVIEW | 0.20 ≤ top < 0.40 | 82 |
| UNCERTAIN | 0.05 ≤ top < 0.20 | 125 |
| NO_RACKET_DETECTED | top < 0.05 | 210 |

明细：`artifacts/unified_3cls_v4/racket_candidates_ps521.csv`（每帧 top_score、框数、状态）。

## 2. 处理决定（写入 V5 数据集）

| 桶 | 处理 | 理由 |
| --- | --- | --- |
| CONFIRMED_CANDIDATE (104) | **写入 racket 候选框**（共 105 个），标记 `AUTO_ASSISTED_RACKET_CANDIDATE` | 有较高置信证据，且目视抽检框落在远端球员持拍位置 |
| NEEDS_REVIEW (82) + UNCERTAIN (125) = **207** | **隔离，不进训练** | 有球拍嫌疑但未确认，若当背景会污染 racket |
| NO_RACKET_DETECTED (210) | 保留（只有 ball + hand 候选） | 无任何球拍证据 |

**没有**把任何自动预测当成人工真值；104 帧的框全部带 `AUTO_ASSISTED` 标记。

## 3. 目视抽检

`artifacts/unified_3cls_v4/visuals/v4_added_racket_candidates.jpg`（12 张，红=racket 候选、
绿=hand 候选、黄=ball GT）。

- 红色框基本落在**远端球员挥拍位置**，方向正确；
- 但框**偏松**（明显大于球拍本体），这是自动标注的典型缺陷 —— 后续训练结果也证实了这一点（见 §5）。

## 4. Hand 候选审核

V3 新增帧的 575 个 hand 框由 hand 专项（conf≥0.45）生成，**本轮未重新审核**，仍是
`AUTO_ASSISTED_HAND_CANDIDATE` / `PENDING_HUMAN_REVIEW`。
目视抽样（`v4_added_frames.jpg`）：绿框落在球员手/臂附近，未发现明显错位，但**没有逐框确认**。

## 5. 自动 racket 标签的实际后果（重要负结果）

把上述 105 个自动 racket 框加入训练后（V4 模型），在**同一个 val** 上：

| 指标 | V3（无自动框） | V4（含自动框） |
| --- | --- | --- |
| Racket AP50 | **0.738** | 0.726 |
| Racket Recall | **0.727** | 0.710 |
| Racket F1 @0.25 | **0.758** | 0.669 |
| Racket FP @0.25 | 42 | **71** |

→ **自动生成的球拍框把 racket 的精度/F1 拉低了**（FP 从 42 涨到 71）。
这是"不能用伪标签直接当真值"的直接实证，也是本轮最有价值的负结论。

## 6. 仍待人工审核的内容

1. 104 帧的 105 个 racket 候选框（偏松，建议人工收紧或删除）；
2. 207 帧被隔离的帧（需要人判断"到底有没有球拍"）；
3. 575 个 hand 候选框；
4. 210 帧"无球拍证据"的帧中是否仍有漏检球拍。

**在这些完成之前，任何用这批数据训练的模型都应视为带标签噪声的候选。**
