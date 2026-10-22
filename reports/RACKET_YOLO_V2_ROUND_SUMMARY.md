# 球拍 YOLO 优化一轮 · 执行摘要

日期：2026-10-21　分支：`codex/c-pc-detector`　HEAD：`58bb405`（未推送）
交付目录：`artifacts/racket_yolo_v2/`（详细报告 7 份，见下）

## 0. 一句话结论

**本轮没有产出可替换部署件的新模型**：新训练的无泄漏 V2（960）在验证集上
AP50 **0.555** < 旧模型 **0.675**，按规则保留旧模型。
但查清了三件实事：① 历史指标被帧级泄漏污染；② 部署阈值 0.30 会丢掉约 30% 真球拍；
③ 没有 C++ 预处理/接口 Bug。

## 1. 资产审计（`RACKET_ASSET_AUDIT.md`）

| 项 | 结果 |
| --- | --- |
| CUDA | ✅ RTX 4060 Laptop 8.6 GB，torch 2.5.1+cu121 |
| 部署 ONNX | `racket_gray_onxx_tmp/racket_yolov8n_gray.onnx` 12,117,766 B `e606e8de…`，输入 `[1,3,640,640]`，输出 `[1,6,8400]`，2 类 |
| 原始 PT | ✅ 存在：`ball_racket_yolov8n_v1/best.pt`（120 轮彩色）、`ball_racket_yolov8n_gray3_v1/best.pt`（60 轮灰度） |
| C++ 链路 | gray3 ✅ / letterbox ✅ / 原图像素 ✅ / 未丢弃球拍框 ✅ / **racket_conf=0.30 偏高** ⚠️ |

## 2. 数据审计（`RACKET_DATA_AUDIT.md`）

- 所有球拍标注都来自同一个 Roboflow tableTennis（7 场比赛）；**没有任何 OV9281/真实球馆球拍标注**。
- **原 train/val/test 是同一批 7 场比赛的随机帧划分**，Match1–6 同时出现在三个集合 → 历史 0.781 AP50 被泄漏抬高。
- 已按比赛重建无泄漏 `RACKET_TARGET_V2`：train Match1–4（1,055 图 / 2,395 球拍框）、
  val Match5（180 / 176）、test Match6（115 / 182）；Match7 无标注 → 排除，不当负样本。
- 球拍尺寸中位 **46.7 px**（p10 35.7 / p90 63.4，1920×1080）→ 典型小目标。
- val 有 71 张空标签图，**未确认是否漏标**，只用于评估，未当负样本。

## 3. 基线诊断（`RACKET_BASELINE_EVALUATION.md`、`RACKET_FAILURE_ANALYSIS.md`）

旧模型（ONNX 640，无泄漏重测）：

| 集合 | AP50 | conf 0.30 P/R/F1 | 真球拍得分 < 0.30 |
| --- | --- | --- | --- |
| val Match5 | 0.675 | 0.761 / 0.580 / 0.658 | **29.7%** |
| test Match6 | 0.898 | 0.940 / 0.857 / 0.897 | 6.6% |

失败模式（可确定的）：远景小球拍（全部 < 80 px，Match5 小球召回 0.564）、
阈值过严（p10 = 0.101）、空帧误检（Match5 的 71 张空标签图 27–45 框）。
运动模糊/遮挡/侧面/定位偏移 → **待确认**（未做逐框人工核查，不强行归类）。
可视化：`visuals/old_val_conf030.jpg`、`visuals/old_val_conf015.jpg`。

## 4. 训练（`RACKET_V2_TRAINING_REPORT.md`）

YOLOv8n，imgsz **960**，AdamW lr 0.0005，mosaic 0.3，degrees 10，seed 42，从 gray3 `best.pt` 微调。
设定 60 轮，**实际 32 轮**（第 19 轮后停滞，按规则停止），best = epoch 19。

- 权重：`artifacts/runs/racket_v2_960/weights/best.pt` 18,483,734 B
  `6e780a27f3c9db9b01063c6604f1a3582eb22f4a1ea413f0d7e33f3ef0f5e0f7`
- ONNX：`artifacts/files/models/racket_v2_960/racket_yolov8n_gray_v2_960_960.onnx` 12,160,334 B
  `a231ff0d0d4600c1e7205aac281f156be918cfbb63381b36d63efcd6b02c1bc5`

## 5. 对比（`RACKET_V2_COMPARISON.md`）

| conf 0.30 | 旧 640 | V2 960 |
| --- | --- | --- |
| val AP50 | **0.675** | 0.555 |
| val P/R/F1 | 0.761 / 0.580 / 0.658 | 0.628 / 0.557 / 0.590 |
| test AP50 | **0.898** | 0.884 |
| test P/R/F1 | 0.940 / 0.857 / 0.897 | 0.874 / 0.835 / 0.854 |

工程期望（P≥0.90、R≥0.90、AP50≥0.90、AP50-95≥0.55）**均未达到**，不宣称达标。
重要限定：旧模型的数字来自**它训练时见过的帧**，V2 才是这套数据上第一次诚实的测量。

## 6. 部署（`RACKET_V2_DEPLOYMENT_REPORT.md`）

- PT/ONNX 一致性：两个模型都通过（sigmoid 差 3.58e-07，top-1 anchor 全一致）。
- CPU 延迟（threads=4）：旧 640 **86.7 ms**，V2 960 **190.2 ms**。
- **建议把 `racket_conf` 从 0.30 降到 0.20–0.25**（Match5 召回 0.580→0.671，F1 0.658→0.694，
  空帧误检 27→34）。不需要重训、不改接口。
- 未改 C++、未改 V2.4 包、未替换部署件、未做 RKNN、**未宣称板端可用**。

## 7. Git

本轮只新增 `artifacts/racket_yolo_v2/`（报告/权重/ONNX/可视化/工具）与本摘要。
`artifacts/` 本就被 `.gitignore` 忽略，**模型与数据集不提交**（符合仓库既有规范）。
本地提交本摘要；**未 push、未建 PR**。

## 8. 最关键的 3 个问题（下一步）

1. **部署阈值 0.30 偏高** —— 立刻可改，收益最大。
2. **没有真实域球拍标注**（目前全来自广播/广角 7 场），队长反馈的场景无法直接验证。
3. **无泄漏训练数据只有 1,055 图**，960 输入下欠拟合；补 Match7 标注或采 200–300 个
   OV9281 真实框，再按比赛重训 60 轮才有机会接近 AP50 0.90。
