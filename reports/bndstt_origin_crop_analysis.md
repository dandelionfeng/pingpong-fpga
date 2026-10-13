# BNDSTT origin / crop 关系核查与训练源建议

核查日期：2026-10-11  
官方来源：<https://huggingface.co/datasets/J0LE/BNDSTT>  
随机种子：`20261011`  
本阶段未运行模型、未生成检测标签、未进行数据集划分。

## 结论摘要

- **应以 `videos/origin` 为 ball / hand / racket 检测的主要数据源。** origin 全部为 `1920x1080`，保留完整球台、发球员和上抛空间，构图也比随人裁剪的 crop 更接近后续固定相机输入。
- **crop 仅建议作为同 group 的辅助视图，不建议单独作为主源。** crop 能明显放大球、手和球拍，但其分辨率和裁剪范围变化很大，且上抛球在部分样本中靠近上边缘或侧边缘，存在被裁出的结构性风险。
- 30 对、360 张抽帧中，未发现能够无歧义确认的“origin 中球清楚可见、同时间比例 crop 中却完全出画”的直接案例；但多组 crop 的球/抛球手已接近边界。因此结论是**存在明显出画风险**，不是声称本次稀疏抽帧已经量化了完整视频中的出画率。
- origin 与 crop 不只是空间裁剪关系：crop 几乎全部被重新编码，并普遍多出 1–3 帧/约几十毫秒；必须按原始 source/session 分组防止派生样本泄漏。

## 1. 对应关系建立方法

完整映射见 `reports/bndstt_origin_crop_mapping.csv`。

匹配按以下证据逐级建立：

1. 将 crop session 名中的 `_yolo_Output_Group1` 规范化为 `_Output_Group1`，要求规范化后的 session 完全一致。
2. 解析文件名中的原始起止时间戳，在同一 session 内寻找起止时间均相差不超过 `0.25 s` 的候选。
3. 只接受 origin→crop 和 crop→origin 都唯一的双向匹配；最大时间差不超过 `0.10 s` 记为 `high`，其余不超过 `0.25 s` 记为 `medium`。
4. 文件名中的 clip index、spin/landing 文本只作为附加证据写入 `match_method`，不强制要求相同。仓库中存在时间区间一致但 clip index 因缺片而偏移、或文件名标签文本不一致的真实条目；若只按相似文件名会误配/漏配。
5. 共享 session 内不能形成双向唯一匹配的条目标为 `unknown`，没有猜测补齐。

### 映射统计

| 项目 | 数量 |
|---|---:|
| origin 视频 | 776 |
| crop 视频 | 992 |
| 明确一一对应（high） | 764 |
| 明确一一对应（medium） | 4 |
| **明确一一对应合计** | **768** |
| 仅 origin（无对应 crop session） | 2 |
| 仅 crop（无对应 origin session） | 202 |
| 共享 session 内仍无法确认关系 | 28（6 origin + 22 crop） |
| 映射 CSV 行数（不含表头） | 1000 |

`source_id` 对确认配对由规范化 session 与 origin/crop clip index 组成；未配对项保留单侧路径和 `unknown`/`origin_only`/`crop_only` 状态。该 ID 是本次审计标识，不应替代未来更保守的 person/session group ID。

### 为什么没有得到“997 对”

- dataset card 的约 997 条是数据集说明口径，不等于当前仓库中两棵视频目录各有 997 条。
- 当前官方快照实际是 992 个 crop、776 个 origin；两者大量是同一发球片段的派生版本，不能相加当作独立样本。
- `annotations/train.txt` 782 行、`annotations/test.txt` 194 行，共 976 行，也与 card 的 997 有小幅差异。
- 根目录 `demo1` 的 2 个 MP4 与 `videos/origin/demo1` 内文件逐字节 SHA256 相同，是重复副本，不是新增 source。
- 另外存在 202 个只有 crop 的条目、2 个只有 origin 的条目，以及共享 session 内 28 个无法可靠配对的条目。综合来看，这是官方仓库版本/目录/标注口径不一致，而非应强行补成 997 对的缺失匹配。

## 2. 30 对抽样与预览

从 31 个具有 high-confidence 配对的 session 中，以固定种子随机选取 30 个不同 session；每个 session 选 1 对，并在候选内兼顾 spin/landing code 覆盖。样本覆盖 spin code `0–7`（另 1 条无对应 annotation code）和 landing code `100–105`（另 1 条无对应 annotation code）。样本没有覆盖 spin code 8；没有为了凑类别而破坏固定随机过程。

每对在 `10% / 25% / 40% / 55% / 70% / 85%` 处分别抽取 origin/crop 帧，共 `30 × 6 × 2 = 360` 张。并排图按同一时间比例而非伪造事件时刻对齐；由于两版时长和帧数略有差异，显示的绝对 timestamp/frame index 可有小偏差。

视角粗略分布为：正面约 10、侧面/近侧面约 3、斜侧约 17。人员和背景覆盖受源数据限制：虽然是 30 个不同 session，但多段仍来自相同场馆和重复出镜者，不能把 30 个 session 当作 30 个独立人物域。

## 3. ball / hand / racket 可见性复核

下表是每段 6 个时间点的**主要限制状态**，不是检测标签。`edge-risk` 表示至少一个抽帧中目标靠近 crop 边缘或活动方向指向边界；它不等同于已确认 `out_of_frame`。

| # | source/session（clip） | ball origin | ball crop | hand origin | hand crop | racket origin | racket crop | crop edge-risk |
|---:|---|---|---|---|---|---|---|---|
| 01 | 20240428_145527 (o00002/c00002) | small | clear | visible | partial | visible | visible | yes |
| 02 | 20240524_185247 (o00004/c00004) | small | clear | visible | visible | visible | visible | no |
| 03 | 20240525_140650 (o00011/c00011) | small | clear | visible | partial | visible | partial | yes |
| 04 | 20240503_162502 (o00024/c00025) | uncertain | small | visible | visible | visible | visible | no |
| 05 | 20240524_184715 (o00008/c00008) | small | clear | visible | visible | visible | visible | no |
| 06 | 20240525_141249 (o00008/c00009) | small | clear | visible | visible | visible | visible | no |
| 07 | 20240428_144126 (o00011/c00012) | blur | blur | visible | partial | visible | visible | yes |
| 08 | 20240526_143307 (o00030/c00030) | small | clear | visible | visible | visible | visible | no |
| 09 | 20240526_142052 (o00006/c00006) | small | clear | visible | visible | visible | visible | no |
| 10 | 20240525_143217 (o00013/c00013) | uncertain | small | visible | visible | visible | visible | no |
| 11 | 20240524_183430 (o00012/c00012) | small | clear | visible | visible | visible | visible | no |
| 12 | 20240525_142724 (o00019/c00019) | small | clear | visible | visible | visible | visible | no |
| 13 | 20240503_164411 (o00009/c00009) | blur | blur | visible | partial | partial | partial | yes |
| 14 | 20240503_163315 (o00012/c00012) | blur | uncertain | visible | visible | partial | visible | no |
| 15 | 20240526_143812 (o00022/c00022) | small | clear | visible | visible | visible | visible | no |
| 16 | 20240524_184245 (o00007/c00007) | small | clear | visible | visible | visible | visible | no |
| 17 | 20240503_163810 (o00005/c00005) | blur | blur | visible | partial | partial | partial | yes |
| 18 | 20240525_135921 (o00039/c00042) | small | clear | visible | visible | visible | visible | no |
| 19 | 20240525_142011 (o00030/c00030) | small | clear | visible | visible | visible | visible | no |
| 20 | 20240524_184951 (o00002/c00002) | small | clear | visible | visible | visible | visible | no |
| 21 | 20240526_141339 (o00009/c00009) | small | clear | visible | visible | visible | visible | no |
| 22 | 20240524_183648 (o00006/c00006) | small | clear | visible | visible | visible | visible | no |
| 23 | 20240526_140724 (o00031/c00033) | small | clear | visible | visible | visible | visible | no |
| 24 | 20240526_142722 (o00006/c00006) | uncertain | uncertain | partial | visible | partial | visible | no |
| 25 | 20240524_184455 (o00012/c00012) | small | clear | visible | visible | visible | visible | no |
| 26 | 20240526_135345 (o00015/c00015) | small | clear | visible | visible | visible | visible | no |
| 27 | 20240428_145028 (o00003/c00003) | blur | blur | visible | partial | visible | partial | yes |
| 28 | 20240524_183130 (o00012/c00012) | small | clear | visible | visible | visible | visible | no |
| 29 | 20240524_185549 (o00011/c00012) | small | clear | visible | visible | visible | visible | no |
| 30 | 20240526_140112 (o00003/c00003) | small | clear | visible | visible | visible | visible | no |

汇总（每视频一个主要状态）：

| 对象 | origin | crop |
|---|---|---|
| ball | small 22；blur 5；uncertain 3 | clear 22；small 2；blur 4；uncertain 2 |
| hand | visible 29；partial 1 | visible 24；partial 6 |
| racket | visible 26；partial 4 | visible 26；partial 4 |
| 确认 out_of_frame | 0 | 0 |
| crop edge-risk | — | 6/30 |

观察：

- 这些片段均表现为短发球动作片段，而非长时间普通相持；多数片段包含持球/抛球、挥拍和随挥阶段。
- origin 中球通常只有数个像素，虽保留完整轨迹空间，但标注难度明显高。crop 常把球放大到更易辨认的尺度。
- 快速运动阶段仍有球和拍的运动模糊，空间裁剪不能消除源视频的模糊。
- crop 对手和球拍主体通常可见，但紧框会降低手臂完全伸展与高抛球的边界余量。稀疏抽帧不能证明完整视频中没有短暂出画。
- 相比最终 OV9281 固定侧视相机，BNDSTT 仍有明显 domain gap：RGB/场馆光照、背景、视角混合、压缩编码、主体尺度和裁剪方式均不同。

## 4. 视频属性差异（全部 768 对确认配对）

| 指标 | 结果 |
|---|---|
| origin 分辨率 | 768/768 均为 `1920x1080` |
| crop 分辨率 | 366 种；0/768 与 origin 相同 |
| 编码 FourCC | origin/crop 全部为 `avc1` |
| 帧数完全相同 | 4/768 |
| 时长差 ≤ 1 ms | 1/768 |
| 时长差 > 10 ms | 767/768 |
| crop 时长更长 / 更短 / 相同 | 764 / 3 / 1 |
| 绝对时长差 min / median / max | 0 / 0.048662 / 0.182993 s |
| crop-origin 帧数差主要值 | +2 帧：420；+3：167；+1：164；0：4 |
| FPS 差 ≤ 0.1 | 101/768 |
| FPS 差 > 1 | 374/768 |
| crop/origin 文件字节比中位数 | 0.5572 |

结论：crop 保留同一 `avc1` 编码家族，但不是对 origin 做无损空间裁剪。它经过重新生成/编码，并通常带有少量时间边界扩展、帧数变化和有效 FPS 差异。因而不能把 origin 与 crop 当成独立采样。

## 5. 数据使用建议与泄漏约束

### A. 主训练源

使用 **origin 作为主训练源**。原因是它保留完整抛球轨迹和上下文、视野一致，且对固定侧视相机的输入形式更自然。其代价是球很小，后续正式标注与训练时需要保留高分辨率信息；本阶段不实施任何训练配置。

### B. crop 的角色

crop **仅作辅助**，不建议单独使用，也不建议把所有 crop 无条件并入主数据：

- 可用于同一 source 的尺度增强、难例复核或手/拍局部细节辅助。
- 对边缘截断、严重紧框、只保留局部肢体的 crop 应排除或降权。
- crop 的可变构图与未来固定相机域不一致；它对小球尺度有价值，但不能代替 origin 的完整轨迹空间。

### C. 防止数据泄漏

未来若同时使用两者，必须在任何帧抽取、标注、增强或 pseudo-label 之前先建立不可拆分的 `group_id`：

`原始 session/source → origin clip + crop clip + 所有抽帧 + 所有人工标签 + 所有后续派生标签/增强版本`

同一 group 绝不允许跨 train、val、independent_test。更保守的做法是优先按 session/人物分组，而不是仅按短 clip 分组；重复 demo 和内容哈希重复视频也必须并入原 group。划分应在 group 层完成，但本阶段**没有实际生成任何 train/val/test 划分**。

## 6. 产物

- 映射表：`reports/bndstt_origin_crop_mapping.csv`
- 并排预览 01：`reports/bndstt_origin_vs_crop_01.jpg`
- 并排预览 02：`reports/bndstt_origin_vs_crop_02.jpg`
- 并排预览 03：`reports/bndstt_origin_vs_crop_03.jpg`
