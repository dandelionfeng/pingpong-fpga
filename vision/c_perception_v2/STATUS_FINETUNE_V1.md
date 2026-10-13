> ## 🟡 SUSPENDED — NOT USED FOR TRAINING
>
> **状态（2026-10-13 用户决定暂停）：**
>
> - `BNDSTT_BR_FINETUNE_V1`（80 张 pool）状态：**SUSPENDED**
> - `human_verified = 0 / 80` —— **没有任何一张通过人工确认**
> - **NOT USED FOR TRAINING**：从未参与任何训练或 fine-tune
> - 8899 标注服务**已停止，不再启动**
> - 全部产物保留（pool / proposals / workspace），便于日后需要时恢复
>
> ⚠️ **给队友的提醒**：这个 pool **不是正式训练数据**。
> proposal 来自模型预标，不是 Ground Truth；未经人工确认的框拿去训练等于伪造标注。
> 当前正式训练数据只有公开的 `tabletennis_ball_racket_v1`。

# BNDSTT DOMAIN FINE-TUNE V1 状态

更新时间：2026-10-13

## 已完成（机器部分，全部可复现）

| 项 | 状态 |
| --- | --- |
| baseline 冻结（未覆盖 v1/best.pt） | DONE，sha256 前缀 `8d1b65e3d424701b` |
| 80 帧确定性选池（排除 benchmark + quick_test） | DONE，benchmark leak = 0 |
| 选池覆盖：27 sessions / 37 sources / 7 阶段（11-12/阶段） | DONE |
| baseline 预标（conf=0.10）：91 ball + 83 racket，6 张零预标 | DONE |
| BR FINETUNE 2 类标注 UI（无 hand，载入预标，保存即 HUMAN_VERIFIED） | DONE，端点已测 |
| 非法类别 / 越界框拒绝校验 | DONE（返回 400） |
| 未确认禁止训练的门禁 | DONE（build 与 train 都拒绝） |
| 两变体训练脚本（BNDSTT-only / mixed replay 30%） | DONE |
| 三模型三处对比 + 阈值扫描 + contact sheet | DONE（baseline 快照已出） |
| duplicate-excluded test 构建与评估 | DONE（见下） |
| out-of-bounds 复核 | DONE：25 个全部为 player 类、越界 0.0005% → 全部 clip，0 drop |

## 阻塞点：80 张人工确认（必须由你完成）

`finetune_domain.py status` 当前显示 `human_verified: 0 / 80`。
按 `ANNOTATION_GUIDE.md` 在 http://127.0.0.1:8899/ 完成确认后，
再依次跑 build → train → eval 三条命令。

**我不会代替你点击“确认”**：proposal 不是 GT，未经人工确认的框放进训练就是伪造标注。

## baseline 快照（BNDSTT_30_V1 @ conf 0.15）

| model | ball | racket | both |
| --- | --- | --- | --- |
| baseline_v1 | 15 | 20 | 8 |

门槛全部未达标（目标 24 / 26 / 22），这正是本阶段要做 fine-tune 的理由。

## 一个重要发现：阈值本身就能显著改善帧检出

对 baseline 做 conf 扫描（BNDSTT_30）：

| conf | ball /30 | racket /30 | both /30 |
| --- | --- | --- | --- |
| 0.05 | 19 | 26 | 17 |
| 0.10 | 16 | 24 | 12 |
| 0.15 | 15 | 20 | 8 |
| 0.25 | 12 | 17 | 5 |

也就是说：**单纯把 conf 从 0.25 降到 0.05，racket 就已达到 26/30 门槛**，
ball 提升到 19/30 但仍不足。这说明两件事：

1. 之前用 conf 0.25 评估域内表现是偏严的；
2. ball 的瓶颈是**置信度不足**而非完全看不见——fine-tune 的价值在于把 ball 的置信度推上去，
   从而在**不牺牲误检**的前提下提高召回。

## duplicate leakage 结论

公开数据仅有 1 组重复图（`Match5_021`，train 与 val 各一份），**test split 未受影响**：
duplicate-excluded 的 mAP50 与原值完全相同（0.7361）。
争议点已量化，无需修改原始数据。