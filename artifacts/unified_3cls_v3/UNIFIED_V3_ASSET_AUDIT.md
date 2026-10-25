# UNIFIED_V3_ASSET_AUDIT — 统一三分类 V3 资产与数据审计

日期：2026-10-25　分支：`codex/c-pc-detector`　起点提交：`4f9c1ea`

## 1. Git 与模型资产（实查）

| 资产 | 路径 | 大小 | 状态 |
| --- | --- | --- | --- |
| 当前统一 V2 权重 | `artifacts/runs/unified_3cls_v2/weights/best.pt` | 6,271,011 B | 基线，**只读引用** |
| 当前统一 V2 ONNX | `artifacts/handoff/UNIFIED_3CLS_V2_FOR_CAPTAIN/pingpong_yolov8n_gray_3cls_v2_960.onnx` | 12,161,114 B | 基线，**不覆盖** |
| Ball 专项 | `artifacts/files/models/ball_fast_v2_scratch/ball_fast_v2_scratch_960.onnx` | 12,159,554 B | 未用于本轮训练 |
| Hand 专项 | `artifacts/files/models/hand_v3_960/hand_yolov8n_gray_final_v3_960.onnx` | 12,159,554 B | **用于生成 hand 候选** |
| Racket 专项 | `artifacts/files/models/racket_gray_onxx_tmp/racket_yolov8n_gray.onnx` | 12,117,766 B | 未用于本轮 |
| Racket 实验权重 | `artifacts/runs/racket_v2b_960_nomosaic/weights/best.pt` | 18,484,950 B | 未用于本轮 |

权重兼容性：V2 `best.pt` 为 3 类 `0=ball,1=hand,2=racket`、`imgsz=960`、2 类数据之外无结构差异，
**可直接续训**，本轮从它初始化。

## 2. 数据资产与规模（本轮实际使用）

| 数据集 | 路径 | 用途 |
| --- | --- | --- |
| pingpong_3cls_v2 | `artifacts/files/datasets/pingpong_3cls_v2` | 上轮 3 类训练集来源 |
| pingpong_unified_3cls_v3 | `artifacts/files/datasets/pingpong_unified_3cls_v3` | 上轮实际训练用的平衡子集（train 3,910） |
| **ball_yolo_v1（ps_*）** | `artifacts/files/datasets/ball_yolo_v1/images/train/ps_*.jpg` | **本轮新增**：521 张 BNDSTT 真实域球帧 |
| RACKET_TARGET_V2 | `artifacts/racket_yolo_v2/dataset/RACKET_TARGET_V2` | 球拍数据的上游（同一批 tabletennis 图像） |

### V4 数据集（本轮新构建）

`artifacts/files/datasets/pingpong_unified_3cls_v4`

| Split | 图片 | ball | hand | racket |
| --- | --- | --- | --- | --- |
| train | **4,431** | **2,499**（+521） | **3,698**（+575 自动候选） | 4,790 |
| val | 509 | 100 | 1,172 | 176 |

- **val 与 V2 完全相同**（同一批 509 图、同一批标签），因此 V2↔V3 对比是公平的。
- ball 框 +26.3%，且新增部分来自**部署域（球馆发球）**。
- 类映射不变：`0=ball, 1=hand, 2=racket`；图像仍为 1920×1080 灰度三通道。
- 构建脚本：`tmp/build_unified_3cls_v4.py`；报告：`pingpong_unified_3cls_v4/build_report.json`。

## 3. 关键缺口（本轮无法消除，如实记录）

| 缺口 | 现状 | 本轮处理 |
| --- | --- | --- |
| tabletennis 帧无 hand 标注 | 2,110 帧只有 ball+racket | 未补（宽视角远处手部，自动补标注不可靠） |
| hand 数据集无 ball/racket 标注 | 1,500 帧只有 hand | 未补（这些是近景手部图，球/拍常不可见或极小） |
| **BNDSTT 球帧无 hand 标注** | 521 帧只有 ball | **用 hand 专项模型补了 575 个候选（conf≥0.45），标记为 AUTO_ASSISTED_HAND_CANDIDATE** |
| BNDSTT 球帧无 racket 标注 | 同上 | **未补**（racket 专项在该域不可靠，避免注入噪声） |
| 独立测试集 | **不存在** | 只能用 val，报告中不使用"测试集"字样 |

## 4. 球/球拍尺寸与来源

- 图像分辨率：统一 1920×1080（源数据已灰度三通道化，与 OV9281 GRAY8→gray3 一致）。
- 球拍：宽中位约 **46.7 px**（p10 35.7 / p90 63.4），占图宽约 2.4%。
- 球：BNDSTT 域中位约 34 px，tabletennis 域 19–31 px。
- 来源：tabletennis（Roboflow tableTennis v2，CC BY 4.0）+ bodyhands（手）+ BNDSTT 采集（球）。

## 5. 划分与泄漏

| 检查 | 结果 |
| --- | --- |
| tabletennis 跨集合 | ✅ 按比赛 M1–M4 / M5 划分 |
| bodyhands 跨集合 | ✅ 按视频 id |
| 新增 BNDSTT 球帧 | ✅ 只进 train，val 未动 |
| 重复图片 | ✅ 新增帧按 `ps_*` 文件名独立，与 val 无交集 |
| 同源增强图 | ⚠ 源数据含 Roboflow 增强变体，沿用其既有划分，未进一步拆分（已知限制） |

## 6. 与 V2 的可比性

- 同一 val（509 图）、同一类别映射、同一预处理（gray3 + letterbox 960）、同一匹配规则（IoU 0.5）。
- 唯一变量：**训练集增加了 521 张真实域球帧（+575 hand 候选）**。
- 因此 V2 vs V3 的差异可以归因到这批数据（以及续训本身）。
