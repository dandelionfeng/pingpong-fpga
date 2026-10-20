# 球检测优化第二轮（BALL_YOLO_V2 / BALL_CROP_V2）：真实域漏检实验

日期：2026-10-21　分支：`codex/c-pc-detector`　上一轮：[BALL_YOLO_V1](BALL_YOLO_V1_REPORT.md)

## 0. 结论

**本轮未达成目标，正式模型与 V2.4 交付包均未改动。**

- 唯一一次冻结测试：裁剪+平铺候选 **4/36**（目标 ≥28/36），比现有 YOLO 的 15/36 更差。
- 但在**验证集**上该候选确实更优（同召回、精度 2.2×、AP50 2×），说明"裁剪/平铺"这条路在
  源域有效、在目标域失效——这是一条有价值的负结论。
- 现有 YOLO（15/36）仍是本任务最好的 YOLO，仍低于 BallTrack 的 28/36。
- **未做**：C++ 接入、正式接口替换、V2.4/R2.4 包修改、推送 main。全部按要求保持原样。

---

## 1. 审计（与上一轮一致，本轮复核）

| 项 | 事实 |
| --- | --- |
| 训练数据 | `ball_yolo_v1`：2738 图 / 2499 球框（989 人工 tabletennis M1–M4，521 BallTrack 伪标签，负样本 239） |
| 验证 | tabletennis **Match5**（180 图 / 100 球框），按比赛隔离 |
| 留出 | tabletennis **Match6**（115 图 / 113 球框），本轮未用于选型 |
| 测试 | `BNDSTT_MANUAL_GT_V1`：42 图 / 36 球框 / 6 空图，5 个 session，**全程排除于训练与伪标签** |
| 泄漏检查 | 训练/验证相同图像 0；tabletennis 比赛无交集；测试 session 未出现在任何训练源 |
| 排除项 | `BNDSTT_YOLO_MVP_V1`（curated 包）：缩略图比对显示可判定帧来自测试 session，禁止使用 |

**球尺寸**：tabletennis 1920 宽等效中位 19–31 px；BNDSTT 中位 34.3 px（24.7–66.8）。
在 1280 全帧输入下，训练域球只有 **13–21 px**——这是本轮要解决的核心。

---

## 2. 伪标签扩充（剩余 18 个非测试 session）

- 使用官方 BallTrack ONNX（输入 `[1,15,288,512]`，灰度三通道复制，背景=片段首帧，
  窗口 `frames[i-4..i-1]`），**逐帧 batch=1**（该图 batch 固定为 1，无法批量）。
- 过滤：`conf ≥ 0.45`、热图连通域 6–120 px、面积 40–9000、前后 2 帧 40 px 内轨迹一致、
  框取**实测连通域**（非固定假框）。
- 结果：**1 个 session 完成，94 个通过过滤的正样本**；随后因两个重任务抢 CPU（每次推理从
  0.19 s 劣化到 ~2.5 s）被主动停止，未跑完 18 个 session。
- 产物：`artifacts/files/datasets/ball_pseudo_v2/`（含 `build_report.json` 未生成，因中断；
  生成日志 `artifacts/runs/build_ball_pseudo_v2.log`）。
- 说明：这 94 个伪标签**未用于本轮训练**（数据集在伪标签中断后按 V1 数据构建），仅作为
  下一轮的可复用输入。

**失败原因（如实）**：BallTrack 单帧推理 190 ms，目标域只有约 13% 的帧有球；要拿到数千个
伪标签需要数万帧推理，与训练争抢同一台机器的 CPU。这是资源约束，不是方法不可行。

---

## 3. 本轮唯一受控实验：原生分辨率裁剪 + 2×2 平铺推理

### 3.1 设计（只改一个变量）

| 变量 | 基线（V1） | 本轮候选 |
| --- | --- | --- |
| 训练输入 | 1920×1080 letterbox → **1280**（球 13–21 px） | **960×960 原生裁剪**（球 19–31 px，相对尺寸 ×1.5） |
| 推理 | 整帧 1280，一次前向 | **2×2 共 4 块 960 图块**，映射回原图后 NMS |
| 其它 | yolov8n、无 mosaic、无 erasing、scale 0.3、lr、数据源、session 隔离 | **完全相同** |

### 3.2 第一版裁剪的缺陷（真实发现）

第一版裁剪**每次把球放在裁剪中心**（抖动 ±160 px）。裁剪验证 mAP50 0.383 看起来不错，
但平铺推理时球常落在图块边缘，模型从未见过 → **Match5 只有 9/100 命中**。

改为**球在裁剪内均匀分布**（距边 40 px）后重训（crop v2，8 轮早停，warm start 自 crop v1）：

| 候选 | M5 命中 | P | R | F1 | AP50 |
| --- | --- | --- | --- | --- | --- |
| V1 全帧 1280，conf 0.10 | 24/100 | 0.214 | 0.240 | 0.224 | 0.0746 |
| V1 全帧 1280，conf 0.05 | 30/100 | 0.092 | 0.300 | 0.138 | 0.0795 |
| crop v1（中心偏差）平铺 | 9/100 | 0.529 | 0.090 | 0.154 | 0.0567 |
| **crop v2（均匀放置）平铺，conf 0.10** | **26/100** | **0.464** | 0.260 | **0.333** | **0.1456** |
| crop v2 平铺，conf 0.05 | **31/100** | 0.316 | 0.310 | 0.313 | 0.1594 |

→ 在**验证集**上，裁剪+平铺用同样的召回把精度提高 2.2 倍、AP50 提高 2 倍。
阈值全部在 Match5 上选（0.10 = 最佳 F1），测试集不参与。

### 3.3 冻结测试（唯一一次，conf 0.10）

| 指标 | crop v2 平铺 | 现有 YOLO（V1 全帧） | BallTrack 参考 |
| --- | --- | --- | --- |
| 球心 ≤50 px 命中 | **4 / 36** | 15 / 36 | 28 / 36 |
| 检出帧 | 31 / 42 | 30 / 42 | 28 / 36 |
| TP / FP / FN | 4 / 38 / 32 | 15 / 48 / 21 | — |
| P / R / F1 | 0.0952 / 0.1111 / 0.1026 | 0.2381 / 0.4167 / 0.3030 | — |
| AP50 | 0.0205 | 0.2282 | — |
| 球心误差中位 / P90（仅命中帧） | 3.59 / 4.76 px | 2.41 / 5.02 px | 7.96 / 24.86 px |
| 空帧误检 | 2 框 | 6 框 | — |

同一冻结运行在 conf 0.05 下（更宽松阈值，仅作透明度参考）：命中 5/36，TP/FP/FN 5/45/31，
P 0.1000 / R 0.1389，AP50 0.0230，中位 3.41 px / P90 4.62 px，空帧误检 3 框。
即**放宽阈值也无法接近 28/36**，不是阈值问题。

**判定：未达标（4/36 ≪ 28/36），且比现有 YOLO 更差。** 冻结测试只跑了这一次，
没有据测试结果回选模型或调阈值；该候选被淘汰，测试集不再重跑。

### 3.4 为什么验证集变好、测试集变差

1. **域差异**：Match5 与训练同属 tabletennis 广播画面；BNDSTT 是球馆实拍（曝光、背景、
   球的高光形态完全不同）。裁剪训练在源域学到的是"广播画面里的白点"，到目标域变成大量误检
   （38 FP / 31 帧有检出）却很少命中真球。
2. **训练不足**：crop v2 只有 8 轮（早停），warm start 自一个已经偏弱的模型（上次 10 轮早停）。
   迁移能力不足，先把源域精度拉起来、目标域召回没跟上。
3. **平铺的代价**：4 块图块各自独立判断，目标域背景复杂时误检成倍增加；实测 2.26 s/帧
   （4 次 960 前向，本机负载下），比整帧 1280 的 72 ms 慢 30 倍。
4. **评测协议缺陷（已修正）**：平铺评估最初把解码下限写成 0.30，低分检测被提前丢弃，
   一度让 crop v2 看起来只有 15/100。改为 0.05 后才有上面的公平对比。该缺陷已记录在
   `artifacts/files/reports/BALL_YOLO_V2/`。

---

## 4. 产物与哈希（不覆盖旧模型）

| 文件 | 大小 | SHA256 |
| --- | --- | --- |
| `artifacts/runs/ball_crop_v1/weights/best.pt`（中心偏差版，保留） | — | — |
| `artifacts/runs/ball_crop_v2/weights/best.pt` | — | `7e6286e04a60b5b83083263d561746dbc0dcedd2c1fde91235d3b2b7e49a46f1` |
| `artifacts/files/models/ball_crop_v2/ball_crop_yolov8n_gray_960.onnx` | 12,159,554 B | `5c42570966b9407f42437f2c2bbc094cc4f7ecb2f94a9229e538ae99c7ecd498` |
| `artifacts/files/models/ball_crop_v1/ball_crop_yolov8n_gray_960.onnx`（旧尝试，保留） | 12,159,554 B | `3f881d77164286b2e16b202e912518f623ccea4dfb4f71947c7a4b99bf6081dd` |
| 现有正式候选 `ball_yolov8n_gray_1280.onnx`（未改动） | 12,218,920 B | `185a337ec9ed6c52e867c3748e889ef8fac56c855ce5cceb478a7213a1f4a17b` |

实验与评测记录：

- `artifacts/files/datasets/ball_crop_v1/`（裁剪数据集 + build_report）
- `artifacts/files/reports/BALL_YOLO_V2/`
  - `onepass_cropv2_tile960_m5_f05.json`（验证集，公平解码下限）
  - `onepass_cropv2_tile960_bndstt.json`（冻结测试，唯一一次）
  - `onepass_crop_tile960_m5.json`（中心偏差版，对照）
- 训练日志：`artifacts/runs/train_ball_crop.log`、`train_ball_crop_v2.log`

---

## 5. 速度

| 方案 | 单帧耗时（CPU） | 备注 |
| --- | --- | --- |
| V1 全帧 1280 | 72 ms | 上一轮实测（20 帧平均） |
| crop v2 + 2×2 平铺 | **2.26 s** | 4 次 960 前向 + 合并；本轮机器负载偏高，属上限 |
| BallTrack 引擎整帧 | 1.2–1.9 s | 参考 |

平铺把速度优势全部吃掉，且精度未提升 → 该路线在目标域不成立。

---

## 6. 下一步决策（供蒲公英选择）

1. **停止在"源域精度"上继续投入**：两轮实验都显示 tabletennis→BNDSTT 的迁移是瓶颈，
   而不是分辨率或增强。继续调裁剪/平铺只会重复本轮结果。
2. **要突破必须补目标域数据**：
   - 你明确不想手标几千张。可行的最小方案是**人工确认 200–300 个球框**
     （从 94 个已有伪标签 + 非测试视频里挑），成本约 1–2 小时，但能显著改变迁移；
   - 或接受"伪标签为主"，但需把 18 个 session 跑完（约 2.5 h CPU 独占），并做伪标签
     与人工框的混合训练——这能在不手标的前提下把目标域样本从 94 提到 2000+。
3. **更现实的工程决策**：ball 继续用 BallTrack（28/36，中位 7.96 px），
   YOLO 只作为**辅助/交叉校验**（它的中位误差 2.4 px 更小，可用于给 BallTrack 结果做
   局部修正，而不是替换）。这条路不增加标注成本，也不需要改冻结接口。
4. 若坚持要 YOLO 替换：先完成"2. 伪标签全量 + 200–300 人工确认"，再重训一轮，
   达标线仍是 ≥28/36 且空帧误检不高于基线。

---

## 7. 复现命令

```powershell
# 伪标签（剩余 session，batch=1）
.\.venv\c-detector\Scripts\python.exe tmp\build_ball_pseudo_v2.py

# 裁剪数据集（球均匀分布）与训练
.\.venv\c-detector\Scripts\python.exe tmp\build_ball_crop_dataset.py
.\.venv\c-detector\Scripts\python.exe tmp\train_ball_crop_v2.py

# 导出 ONNX（需要在有 onnx 模块的解释器里执行）
D:\Python\python.exe tmp\export_ball_crop.py ball_crop_v2

# 验证集：平铺 + 阈值扫描（只用于选阈值）
.\.venv\c-detector\Scripts\python.exe tmp\eval_ball_onepass.py `
  --onnx artifacts\files\models\ball_crop_v2\ball_crop_yolov8n_gray_960.onnx `
  --dataset m5 --mode tile960 --tag cropv2_tile960_m5_f05

# 冻结测试（仅在模型冻结后执行一次）
.\.venv\c-detector\Scripts\python.exe tmp\eval_ball_onepass.py `
  --onnx artifacts\files\models\ball_crop_v2\ball_crop_yolov8n_gray_960.onnx `
  --dataset bndstt --mode tile960 --tag cropv2_tile960_bndstt
```
