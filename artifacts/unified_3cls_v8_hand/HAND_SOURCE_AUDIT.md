# HAND_SOURCE_AUDIT — Hand 数据与模型资产审计

日期：2026-10-29　分支：`codex/c-pc-detector`　起点提交：`99fe08e`

## 1. 模型资产（实查）

| 资产 | 路径 | 大小 | SHA256 |
| --- | --- | ---: | --- |
| **V3 统一权重** | `artifacts/runs/unified_3cls_v3b/weights/best.pt` | 6,271,011 | `35e72c114e5c0fe5dc822cd826a5aa6be303bc6516d38317979b71bc5e455b23` |
| **V3 ONNX（当前推荐）** | `artifacts/files/models/unified_3cls_v3b/pingpong_yolov8n_gray_3cls_v3_960_960.onnx` | 12,161,114 | `b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba` |
| Hand 专项 ONNX | `artifacts/files/models/hand_v3_960/hand_yolov8n_gray_final_v3_960.onnx` | 12,159,554 | 单类 hand（未参与本轮训练） |

## 2. 训练数据（V3 实际使用）

| 项 | 值 |
| --- | --- |
| 数据根 | `artifacts/files/datasets/pingpong_unified_3cls_v4`（`data.yaml` 存在，nc=3） |
| train | 4,431 图（ball 2,499 / hand 3,698 / racket 4,790 框） |
| val | 509 图（ball 100 / hand 1,172 / racket 176 框） |
| 类别 | `0=ball, 1=hand, 2=racket` |
| 训练配置 | YOLOv8n 960, batch 12, AdamW 3e-4, 16 epoch 设定 / 15 实跑, best epoch 9, 32 min |

## 3. Hand 数据来源拆解（关键）

| 来源 | 前缀 | 图像数 | hand 框 | 分辨率 | 实际场景 |
| --- | --- | ---: | ---: | --- | --- |
| bodyhands | `bh_*`（val 为 `vbh_*`） | 3,000 中抽 700 | 大 | **480×360 等小图** | ⚠ **影视剧画面**（TV/电影），非乒乓 |
| hand_pseudo | `pp_*` | 1,549 中抽 400 | 中 | 混合 | 伪标签/派生 |
| hand_synthetic | `sy_*` | 800 中抽 400 | 中 | 合成 | 合成增强 |
| BNDSTT 球帧的 hand 候选 | `ps_*` | 521 | 575（自动） | 1920×1080 | 球馆（部署域），**但为模型自动标注** |
| tabletennis 帧 | `tt/tt2_*` | 2,110 | **0** | 1920×1080 | 球台广角，**完全没有 hand 标签** |

### 3.1 最关键发现

**Hand 的验证集（400 张 `vbh_*`）是影视剧画面**——目视抽查 6 张（`visuals/val_hand_gt_sheet.jpg`）：
病房、影院观众席、街头、树林，多种人物。这**与乒乓发球场景毫无关系**。

**且这些图的标注是"只标关注的手"**：同一张图里明显有多只手/手臂，却只框了 2–3 个。
例如观众席那张，画面里至少 6–8 只可见的手，只有 3 个框。

→ 后果：模型检出真实但未标注的手会被记为 FP。**Hand 的 P=0.691 是系统性低估**。

## 4. 标签完整性

| 数据集 | Ball | Hand | Racket | 完整性判定 |
| --- | :---: | :---: | :---: | --- |
| bodyhands（bh/vbh） | ✗ | ✓（部分） | ✗ | **INCOMPLETE_LABELS**（手也不完整） |
| hand_pseudo / synthetic | ✗ | ✓ | ✗ | INCOMPLETE_LABELS |
| tabletennis（tt） | ✓ | **✗** | ✓ | INCOMPLETE_LABELS（缺 hand） |
| BNDSTT 球帧（ps） | ✓ | 自动候选 | **✗** | INCOMPLETE_LABELS（缺 racket，hand 非人工） |

**没有任何一个数据源同时具备完整、人工确认的三类标注。**

## 5. 尺寸分布（val 的 hand GT，原图像素）

| 桶 | FN 数 | 占 FN |
| --- | ---: | ---: |
| < 48 px | **400** | **77%** |
| 48–95 px | 97 | 19% |
| 96–191 px | 17 | 3% |
| ≥ 192 px | 4 | 1% |

→ Hand 漏检**主要由极小手主导**（影视剧远景中的小人手）。

## 6. 泄漏与隔离

| 检查 | 结果 |
| --- | --- |
| val 是否进训练 | 否（V8 训练集只来自 train 侧） |
| 是否用 val 采样 | 否 |
| 重复图 | V8 仅对 `1 in cls and 0 not in cls` 的 1,500 帧做 1 份副本（曝光放大，非新数据） |
| 影视剧帧是否与乒乓域混用 | 是（既有问题），已在报告中标注为域不一致 |

## 7. 结论

1. **Hand 的可测量集（val 509 中的 400 张）是影视剧域**，其 F1 不能代表乒乓部署表现；
2. Hand 标签**系统性不完整**（只标关注的手），P 被低估；
3. 乒乓部署域里**几乎没有人工 hand 标签**（仅 575 个自动候选）；
4. 因此本轮可以做的"Hand 提升"只能是在**这个代理域**上做，**不能宣称提升乒乓场景的 hand 检测**。
