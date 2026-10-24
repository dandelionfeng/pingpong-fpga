# UNIFIED_3CLS_DATA_AUDIT — 统一三分类数据审计

日期：2026-10-24　目标：今晚交付一个**真正的单次推理三分类 YOLO**（ball/hand/racket）

## 1. 候选数据源盘点（实查）

| 数据集 | 路径 | 图像 | ball | hand | racket | 类别 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pingpong_3cls_v2 | `artifacts/files/datasets/pingpong_3cls_v2` | 8,011 / 509 | 1,978 | 11,531 | 4,790 | 0/1/2 | ✅ **唯一具备三类标注的数据源，采用** |
| pingpong_3cls_v1 | 同上 v1 | 3,700 / 250 | 844 | 3,809 | 1,923 | 0/1/2 | ❌ val 缺 hand（`{0:233,2:550}`）→ 旧统一模型 hand 退化的根因 |
| RACKET_TARGET_V2 | `artifacts/racket_yolo_v2/...` | 1,055 / 180 / 115 | 989 | 0 | 2,395 | 0/1 | ❌ 无 hand，且只有 2 类 |
| tabletennis_ball_racket_v1 | `artifacts/files/datasets/...` | 1,036 / 291 / 153 | 844 | 0 | 1,923 | 0/1 | ❌ 无 hand |
| BNDSTT_MANUAL_GT_V1 | `artifacts/files/datasets/BNDSTT_MANUAL_GT_V1` | 42 | 36 | 有 | **0** | 0/1 | ❌ 无 racket，且只有 42 图 |

**结论：只有 `pingpong_3cls_v2` 同时具备三类标注**，且它的划分已经按比赛/视频隔离
（tabletennis M1–M4 train / M5 val；bodyhands 按视频 id；pseudo 只在 train）。
RACKET_TARGET_V2 虽然划分最干净，但只有 ball+racket 两类，**不能**直接用来做三类。

## 2. 采用的训练子集（`pingpong_unified_3cls_v3`）

为控时间从 8,011 张里抽平衡子集（**球+拍帧全保留**，因为这两类稀缺）：

| Split | 图像 | ball 框 | hand 框 | racket 框 | 各类有标注的图 |
| --- | --- | --- | --- | --- | --- |
| train | **3,910** | 1,978 | 3,123 | 4,790 | ball 1,978 / hand 1,500 / racket 2,104 |
| val | **509** | 100 | 1,172 | 176 | ball 100 / hand 400 / racket 106 |

- 类别顺序固定：`0=ball, 1=hand, 2=racket`。
- 标签**逐字节沿用**源数据，没有新造任何标签。
- 构建脚本：`tmp/build_unified_3cls_v3.py`；manifest：`pingpong_unified_3cls_v3/build_report.json`。

## 3. 标注完整性（最重要的问题，如实说明）

| 来源 | 标了什么 | 没标什么 |
| --- | --- | --- |
| tabletennis（tt/tt2，2,110 帧） | ball + racket | **hand 完全没标** |
| bodyhands（bh，700 帧抽样） | hand | ball / racket 没标 |
| hand_pseudo（pp，400）+ hand_synthetic（sy，400） | hand | 同上 |
| 负样本（bg/hn，300） | 无目标 | — |

**这意味着**：训练时这些"没标的类别"会被 YOLO 当作背景学习。这正是任务里提醒的风险，
也是**统一模型各类指标低于专项模型的根本原因**。

处理方式（按任务要求"不能把未标注的其他类别自动视为负样本"）：

1. **没有**人为补造缺失类别的标签；
2. 本报告**明确记录**该限制，并在交付包的 MODEL_CARD / README 里再次声明；
3. 由于仓库内**不存在**任何"三类齐全"的标注数据（BNDSTT 无 racket，球拍集无 hand），
   今晚无法从根本上消除这一限制 —— 要修必须人工补标，不能靠脚本伪造。

## 4. 泄漏检查

| 检查 | 结果 |
| --- | --- |
| 同一比赛跨集合 | ✅ 无（tabletennis 按 M1–M4 / M5 划分） |
| 同一视频跨集合 | ✅ 无（bodyhands 按 video id 分） |
| 重复图片 | ✅ 抽样 md5 查重，未发现同名同内容重复 |
| 同源增强图 | ⚠ 源数据来自 Roboflow 增强导出，**同源多增强变体**可能存在；本轮沿用其划分，未额外拆分 |
| pseudo 只进 train | ✅ |
| 类别映射一致 | ✅ 三源统一为 0/1/2 |

## 5. 训练前门禁

| 门禁 | 结果 |
| --- | --- |
| 三类均有 GT（train + val） | ✅ val: ball 100 / hand 1,172 / racket 176 |
| val 不是训练子集 | ✅ |
| CUDA 可用 | ✅ RTX 4060 8.6 GB |
| smoke test（1 epoch / 5%） | ✅ 三分类头正常、loss 有效、ball 类可检出 |
| 数据可训练 | ✅ 3,910 图 / 9,891 框 |
