# C 端感知 V2：ball + racket 检测 + Pose 手腕

本目录是 C 端视觉模块的**新方案**（2026-10 起）。它**取代**旧的
`vision/bndstt_mvp`（ball/hand/racket 三类）路线，但**不删除、不修改**旧模块，
旧 `DetectionResult`（`boxes: ball|hand|racket`）继续可编译、可运行。

## Architecture

```text
YOLOv8n           -> ball + racket            （检测器 A，2 类目标检测）
YOLOv8n-Pose      -> left_wrist / right_wrist （检测器 B，COCO 17 关键点，index 9/10）
        downarrow
Temporal association -> racket wrist / toss wrist （HEURISTIC 候选判定，非 Ground Truth）
        downarrow
B module          -> release / apex / contact / height / legal judgement
```

### hand 类已经取消

- 不再训练 `hand` / `toss_hand` / `racket_hand`；
- 不再要求人工标 280 张 hand；
- 不让 YOLO 直接判断“哪只是持拍手 / 哪只是持球手”；
- 手腕身份由 **时序关系** 判定：靠近 racket 且在连续帧稳定关联的 wrist → racket hand，
  另一只 → toss/free hand；
- Pose 输出的是**手腕关键点**，不是 hand bbox。代码里不会围绕手腕伪造方框。

## 数据

| 项 | 值 |
| --- | --- |
| 公开数据 | Roboflow Universe `tabletennis-nbcdc`，作者 `yolo class`，**version 2** |
| 原始类别 | ball / table / player / net / racket / scoreboard / umpire |
| 转换后 | `0 ball`、`1 racket`（其余类别丢弃标签，图片保留为合法负样本） |
| 划分 | 保持原始 train / valid / test，**不重新随机划分** |
| License | CC BY 4.0 |
| 域内 benchmark | `BNDSTT_30_V1`（固定 30 帧，冻结，可复用比较） |

原始数据与转换结果全部落在被 Git 忽略的 `artifacts/files/datasets/` 下；
数据源记录写入 `tabletennis_ball_racket_v1/SOURCE.md`。

## 目录内容

| 文件 | 作用 |
| --- | --- |
| `config.py` | 路径 / 常量 / 数据源元数据 / Git 忽略自检；`dataset.yaml` 用绝对路径 |
| `yolo_io.py` | 归一化 ↔ 原图坐标转换、框校验、统一绘图层与配色 |
| `data_prep.py` | ZIP 获取与解压（Zip Slip 防护）、RAW 审计、二分类转换、SOURCE.md |
| `dataset_qa.py` | BR 数据集读取、GT QA contact sheet、ball 尺寸分布 CSV |
| `ball_racket.py` | 检测器 A；`PerceptionResultV2`（独立结构，不动旧 API） |
| `wrist_pose.py` | 检测器 B；COCO 17 关键点，`left_wrist=9`、`right_wrist=10` |
| `fusion.py` | 单帧 HEURISTIC 关联 + 时序关联 + 三视图可视化 |
| `fusion_demo.py` | `fusion` 的入口别名（两个模块名都可用） |
| `bndstt_benchmark.py` | `BNDSTT_30_V1` 确定性构建与冻结校验 |
| `latency_bench.py` | GPU 延迟 / 吞吐测量（warmup 20 + 100 次迭代，mean/median/P95） |
| `prepare_tabletennis_br.py` | Stage 1-3 入口（获取 → 审计 → 转换 → QA） |
| `train_ball_racket.py` | Stage 4-5 入口（GPU smoke → 训练 smoke → 正式训练） |
| `eval_ball_racket.py` | Stage 6 入口（test split 指标 + tiny-ball 失败分析） |

## 快速开始

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"

# 单元测试（30 项）
& $python -m pytest tests\test_c_perception_v2.py -q

# 固定 benchmark（已生成则拒绝覆盖）
& $python vision\c_perception_v2\bndstt_benchmark.py verify

# Stage 1-3：获取 v2、审计、转换、QA
& $python vision\c_perception_v2\prepare_tabletennis_br.py --auto

# Stage 4-5：GPU smoke + 训练（batch 16 -> 8 -> 4 自动降级）
& $python vision\c_perception_v2\train_ball_racket.py

# Stage 6：test split 正式评估
& $python vision\c_perception_v2\eval_ball_racket.py

# Stage 7：BNDSTT 30 联合可视化
& $python vision\c_perception_v2\fusion_demo.py

# Stage 8：延迟基准
& $python vision\c_perception_v2\latency_bench.py --also-cpu
```

## 硬约束（不要违反）

1. `dataset.yaml` 的 `path:` 必须是**绝对路径**（Ultralytics 会把相对 path 拼到全局
   `datasets_dir`，旧方案在这里踩过坑）；
2. 所有最终 bbox / wrist 都是**原图坐标**，禁止把 640 letterbox 坐标当输出；
3. 下载到的数据不是 1480 张就**停止训练**，先查是不是误拿 v1 或被自动 augmentation；
4. `quick_test` 的 5 个视频继续冻结：不训练、不调参、不做模型选择、不看；
5. 旧 `BNDSTT_MANUAL_GT_V1`（含 hand 标签）只作为只读参考，**不进入公开数据训练**；
6. Roboflow API key 只从环境变量 `ROBOFLOW_API_KEY` 读取，绝不落盘、绝不打印；
7. 本轮不做 RKNN 转换、不做板端测试；公开页面的 mAP 不是本项目指标。

## 指标口径

- 本项目模型的指标一律由 `eval_ball_racket.py` 在 v2 **test split** 上重测；
- Roboflow 公开页面的 mAP50 87.4% / Precision 92.0% / Recall 85.6% 属于**页面指标**，
  只能作为参考，不能写成“我们的指标”；
- BNDSTT 域内结果一律标注为**域内定性/候选**结果，因为该域人工 GT 目前只有 42 张，
  且不含 racket 标签。

## Inference Operating Point

ball 与 racket 的任务需求不同，因此**支持 class-specific confidence**，不共享同一阈值：

```python
detections = detector.predict(image, conf=0.02)          # base_conf：一次推理缓存全部候选
balls    = [d for d in detections if d.cls == 0 and d.conf >= ball_conf]
rackets  = [d for d in detections if d.cls == 1 and d.conf >= racket_conf]
```

阈值在 Python 后处理套用，切换阈值**不需要重跑 GPU**。

### 三个 profile（公开 test 固定阈值指标，IoU 0.50，one-to-one greedy）

| profile | ball_conf | racket_conf | ball P/R/F1 | racket P/R/F1 | BNDSTT_30 coverage (ball/racket) |
| --- | --- | --- | --- | --- | --- |
| PROFILE_HIGH_RECALL | 0.03 | 0.05 | 0.4524/0.76/0.5672 | 0.554/0.8429/0.6686 | 21/30 / 26/30 |
| PROFILE_BALANCED | 0.05 | 0.3 | 0.557/0.704/0.6219 | 0.7897/0.7643/0.7768 | 19/30 / 17/30 |
| PROFILE_HIGH_PRECISION | 0.25 | 0.4 | 0.8791/0.64/0.7407 | 0.834/0.7357/0.7818 | 12/30 / 13/30 |


**RECOMMENDED DEFAULT**：`ball_conf = 0.05`，`racket_conf = 0.3`（见 `artifacts/files/reports/OPERATING_POINT_V1/recommended_operating_point.json`）。

注意：

- 该建议文件**不会自动修改任何生产默认配置**；
- `AP50 / mAP50 / mAP50-95` 仍是模型整体指标，**不会**对固定阈值再算一遍 mAP（概念错误）；
- BNDSTT_30 上没有完整 verified GT，因此只能报 **detection coverage**，
  **禁止**报 recall / precision / AP。

### 为什么 BALANCED 不直接取公开 test 最优

BNDSTT 域内置信度**系统性偏低**：racket 在公开 test 上 F1 最优是 conf 0.40，
但同一阈值在 BNDSTT_30 上 coverage 只有 13/30。BALANCED 规则因此把
**域内 coverage 下限**作为硬约束（ball ≥ 19/30，racket ≥ 17/30）。

## Temporal Association

连续视频上的 tracking-by-detection，三种状态**严格区分**：

| 状态 | 含义 | 是否算“检测到” |
| --- | --- | --- |
| `DETECTED` | 当前帧有 candidate（conf ≥ 工作阈值）且被 track 接受 | 是 |
| `RECOVERED_LOW_CONF` | 当前帧**确实有** candidate（base_conf ≤ conf < 工作阈值）且通过运动 gate | 是（低置信恢复） |
| `PREDICTED_ONLY` | 当前帧**没有**被接受的 candidate，只有 Kalman 预测 | **否** |

实现：`temporal_diagnostic.py`（`SIMPLE3` / `SIMPLE5` / `KALMAN` 三个变体，全部 **CAUSAL**，算法延迟 0 帧）。

关键约束：

- **因果**：只用 t, t-1, t-2 …，不访问未来帧；
- 不允许把 `PREDICTED_ONLY` 当成检测或 recovery；
- 第一版 `max_prediction_gap = 2`，不允许长时间无候选仍称 track 正常；
- 时序成本约 0.7074 ms/clip（≈0.2 ms/帧），不是 60 FPS 的瓶颈。

### 两个 benchmark 的角色不同（不要混用）

| 数据集 | 帧结构 | 用途 | 允许的指标 |
| --- | --- | --- | --- |
| `BNDSTT_30_V1` | 30 帧来自 **30 个不同 source**，**不是连续序列** | 单帧 domain detection **coverage** | coverage / candidate count |
| `BNDSTT_TEMPORAL_DIAGNOSTIC_V1` | 8 段**段内真正相邻**的连续帧（共 324 帧） | temporal candidate association **diagnostic** | continuity / dropout / track break |

**禁止**在 `BNDSTT_30_V1` 上做 3/5 帧平滑、max-vote 或 Kalman 评测 —— 那是方法学错误（帧不连续）。

`BNDSTT_TEMPORAL_DIAGNOSTIC_V1` 是 **UNLABELED DIAGNOSTIC SET**，不是 accuracy benchmark：
它没有逐帧 GT，因此在该集上**禁止**报告 precision / recall / AP / accuracy / TP / FP，
只能报告 candidate coverage、dropout、track continuity 等结构性指标。

命令行：

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"
& $python vision\c_perception_v2\temporal_benchmark.py verify      # 校验冻结 manifest
& $python vision\c_perception_v2\temporal_benchmark.py probe       # 查看可选 clip（只读）
```

## 关于 sharpness / motion blur 的严格表述

> 当前 baseline 对已有运动模糊并不敏感；在该公开 test split 上，较低 Laplacian sharpness 的样本检测率反而更高。该现象是相关性结果，尚不能推出主动增加曝光或运动拖影会提高检测性能。摄像头曝光策略暂不调整——后续还需考虑球中心定位精度、双目匹配精度与轨迹估计误差，不应为了单帧 detector recall 主动制造拖影。

详细分析与推理见 `artifacts/files/reports/BALL_FAILURE_ANALYSIS/ball_failure_report.md`。

## Suspended / Deprecated（2026-10-13）

| 项 | 状态 |
| --- | --- |
| `BNDSTT_BR_FINETUNE_V1`（80 张 fine-tune pool） | **SUSPENDED / NOT USED FOR TRAINING**（`human_verified = 0`） |
| 8899 标注服务 | 已停止，不再启动 |
| hand / toss_hand / racket_hand 类别 | **永久取消**，不再训练 hand detector |
| `ball + hand + racket` 三分类 V2 方案 | **取消**，正式方案为 `ball + racket` + pose 手腕关键点 |
| 旧 29-image ChatGPT GT 实验（`reports/C_DETECTOR_MVP_V1.md`） | **DEPRECATED / INVALID FOR FINAL EVALUATION** |
| `vision/bndstt_mvp/` 手工标注工具 | LEGACY（历史工具，非当前 pipeline） |
| `BNDSTT_MANUAL_GT_V1` | 只读；**禁止用于训练** |
| `artifacts/quick_test` | **完全冻结，未修改** |

### 为什么 fine-tune pool 被暂停

该 pool 的 80 张图只有**模型预标（MODEL_PROPOSAL）**，`human_verified = 0 / 80`。
proposal 不是 Ground Truth。把未确认的框当训练数据就是伪造标注，因此 `finetune_domain.py build`
与 `train_finetune.py` 都会**主动拒绝**执行。任务要求零人工标注，所以本轮保持 SUSPENDED，
全部产物保留以便日后恢复。
