# 球检测第三轮（DRYAD_BALL_V1）：Dryad 数据接入、训练与冻结评测

日期：2026-10-21　分支：`codex/c-pc-detector`　上轮：[BALL_YOLO_V2](BALL_YOLO_V2_REPORT.md)

## 0. 结论

**未达标，Dryad 候选明显劣于现有 YOLO，BallTrack 继续作为正式 ball 后端。**

| 模型 | 冻结 BNDSTT 命中 | TP/FP/FN | P | R | AP50 | 中位/P90 误差 | 空帧误检 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **BallTrack（参考）** | **28/36** | — | — | — | — | 7.96 / 24.86 px | — |
| 现有 YOLO（BALL_YOLO_V1） | **15/36** | 15/48/21 | 0.2381 | 0.4167 | 0.2282 | 2.41 / 5.02 px | 6 框（3 帧） |
| 本轮 Dryad-only（no-BlurBall 臂） | **4/36** | 4/28/32 | 0.1250 | 0.1111 | 0.0420 | 1.46 / 2.39 px | 0 框 |
| 本轮 Dryad+BlurBall 臂 | 未送入冻结测试 | — | — | — | — | — | — |

- 冻结测试只执行了 1 次（对 Dryad-only 臂，因它在 Dryad 验证集上召回更高）。
- **未导出交付 ONNX、未改 C++、未动 V2.4 包与 Release、未推送 main、未训练球拍。**
- 本轮唯一新增的模型文件是**评测用途**的 `dryad_eval_only/dryad_noblur_1280.onnx`，不属于交付物。

---

## 1. 数据下载与审计

### 1.1 Dryad（主数据集）

| 项 | 值 |
| --- | --- |
| 记录 | `doi:10.5061/dryad.3bk3j9m13` v3《A high-quality sport ball dataset annotation based on videos》 |
| 下载 | `https://datadryad.org/api/v2/versions/439548/download`（整版 zip，9,143,733 B） |
| 整版 zip SHA256 | `3e7f20919f31822ba77c2a64a6474f4194894cd38d66007eb05ecf03e7ec273b` |
| `tableTennis.zip` | 3,491,226 B，SHA256 `ef6a424c9618235a7afebdee86fcc40e2a44304a3ba843e7238b3fc9a3edf45c` |
| **内容性质** | **只有标签**（15,936 个 `.txt` + 6 CSV + 3 README），**没有图像** |
| 图像/视频 | Zenodo 记录 `10.5281/zenodo.19874311`（record 19874312），单 zip 1,726,054,270 B |
| 视频 zip 校验 | 本地 SHA256 `f70cfd7eb59d19aa6a545e050b6f1f6ee9076016c51b53e8b69530037aebf8e3`；本地 MD5 `afd1ef768d40702f710d475310d02ab6` **与 Zenodo 公布 MD5 一致** |
| 许可 | 标签 CC0（Dryad）；**视频 CC BY-NC-ND 4.0**（zip 内 LICENSE.md，非商用、禁止演绎）。非商用研究/竞赛用途，数据仅本地保存，**不进 Git、不再分发** |

下载过程（如实）：直连 Zenodo 只有 40 KB/s（预估 11.6 h），改用本机代理后 0.66–1.7 MB/s，
约 20 分钟完成；使用 `curl -C -` 断点续传。

**标签语义审计**（`artifacts/files/reports/DRYAD_AUDIT/label_audit.json`）：

| 子集 | 序列 | 帧数 | 球框 | 无效行 | 空标签文件 | 球宽×高（1920×1080 等效中位） | 长宽比 p90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Blurball | 7 | 5,490 | 5,549 | 0 | **0** | 24.0 × 18.0 px | 2.22 |
| BMN | 2 | 3,541 | 3,541 | 0 | 0 | 15.0 × 16.5 px | 2.77 |
| default | 9 | 5,593 | 5,611 | 0 | 0 | 22.5 × 14.0 px | 2.25 |
| FMO | 3 | 795 | 872 | 0 | 0 | 67.0 × 25.0 px | 2.79 |
| openTT | 1 | 517 | 517 | 0 | 0 | 20.0 × 16.0 px | 1.88 |
| **合计** | **22** | **15,936** | **16,090** | **0** | **0** | — | — |

- 格式：Ultralytics `cls cx cy w h`（归一化），**所有实例 class 0**；坐标合法率 100%。
- 标签文件名后缀 = **视频帧号（0 起）**，但**索引是稀疏的**（例如 openTT 只标 681..1615）。
  **缺失的标签文件表示"该帧未标注"，绝不能被当成"无球"负样本**——第一版构建器就是这么错的，
  已修正并重建。
- 长宽比 p90 1.9–2.8：大量**运动模糊拉长框**，正是本项目缺的属性。
- 重复标签文件 141 个（内容完全相同）。
- 球尺寸与 BNDSTT 真值（中位 34.3 px）比更小（15–24 px），与 tabletennis 旧数据（19–31 px）同量级。

### 1.2 BlurBall（补充数据集）

| 项 | 值 |
| --- | --- |
| 官方仓库 | https://github.com/cogsys-tuebingen/blurball（MIT，代码；权重与数据集在 NextCloud） |
| 数据集划分 | 25 场比赛，官方配置 **train=match 00–21 / test=22–25**（按比赛分组，天然防泄漏） |
| 标注语义 | 球位置 + 显式模糊（长度、方向），把球放在模糊中心 |
| 本轮处理 | **未单独下载**：Dryad `tableTennis/Labels/Blurball/` 已按 YOLO 格式提供其 7 个片段（5,490 帧，审计 0 无效行），直接作为 "Dryad+BlurBall" 臂使用，避免了数 GB 的重复下载 |
| 结论 | 转换可靠（Dryad 已代为转换），因此纳入对照实验；独立 NextCloud 副本未使用 |

### 1.3 与已有资产的关系

未重复下载/重复标注：`BALL_YOLO_V1`（tabletennis + 521 个 BNDSTT 伪标签）、`ball_pseudo_v1/v2`
（上轮 94 个伪标签）保持原样；本轮只新增 `dryad_tt/`（原始下载与解压）与 `dryad_ball_v1/`（转换后数据集）。

---

## 2. 数据集构建（防泄漏）

`artifacts/files/datasets/dryad_ball_v1/`：

| 项 | 值 |
| --- | --- |
| 抽帧 | 每 3 帧取 1（stride 3），灰度三通道复制，JPEG q92，原生 1920×1080（BMN 为 1280×720） |
| train（all 臂） | **4,761 张**（其中不含 Blurball 的 **3,069 张**） |
| train 球框 | **4,567**（含 239 个负样本图，见下） |
| val | **771 张 / 777 球框** |
| 划分方式 | **按整段视频分组**：val = `default_06` + `Blurball/01_001`，其余视频全部进 train；同一视频的帧不会跨集 |
| 负样本 | Dryad **没有**空标签文件（全部标注帧都有球），因此两个臂**共用同一组固定负样本**（沿用 V1 的 239 张：非测试 BNDSTT 背景 + tabletennis Match7），保证两臂 FP 控制条件相同 |
| 未标注帧 | 直接跳过，**不当作负样本** |
| BNDSTT 隔离 | 5 个测试 session 完全未参与本轮任何数据、训练或选型 |

两个清单（同一份图像池，硬链接实现，不额外占盘）：`data_all.yaml`（含 Blurball）/ `data_noblur.yaml`。

> 构建过程中修掉两个真实缺陷：① 缺失标签文件被误当负样本（会引入错误监督）；
> ② `train.txt` 图像清单因中文路径用系统默认编码读取而无法被 ultralytics 加载，
> 改为硬链接目录。

---

## 3. 训练

两个臂配置完全一致，只差是否包含 BlurBall 帧；均 warm-start 自 `BALL_YOLO_V1/best.pt`。

| 项 | 值 |
| --- | --- |
| 模型 / 输入 | YOLOv8n / **1280**（沿用已验证配置，不改架构与推理方式） |
| 增强 | mosaic **0**、erasing 0、scale 0.3、fliplr 0.5、hsv_h/s 0（灰度）、hsv_v 0.4 |
| 优化 | lr0 0.005、lrf 0.02、cos_lr、warmup 0.5、batch 8、AMP、seed 42、patience 3 |
| 轮数 | 每臂 **5 轮**（未触发早停，时间预算内取 5 轮） |
| 硬件 | RTX 4060 Laptop 8 GB ≈ 4.1 GB 显存 |
| 耗时 | no-BlurBall 臂 ≈ 11 min；all 臂 ≈ 17 min |

| 臂 | best epoch | P | R | mAP50 | mAP50-95 |
| --- | --- | --- | --- | --- | --- |
| Dryad-only（no-BlurBall） | 5 | 0.9143 | **0.7685** | 0.8031 | 0.4331 |
| Dryad+BlurBall | 5 | 0.9285 | 0.7400 | 0.8057 | 0.4345 |

两臂在 Dryad 验证集上几乎打平（mAP50 差 0.003、mAP50-95 差 0.001）；按"命中优先"选召回更高的
**Dryad-only 臂**进入冻结测试。BlurBall 在本预算下**没有可测收益**。

权重 SHA256：

- `dryad_ball_noblur/weights/best.pt`：`8835c47d3360f1d897195edbe9d2ea08d657ec8ef4fae29086297eb55edd2182`（6,310,819 B）
- `dryad_ball_all/weights/best.pt`：`91c1f679ce8813a615f5650cd28f05f9076a146682266dd0410e63d981efd462`（6,310,819 B）

---

## 4. 冻结测试（唯一一次）

评测口径与历轮一致：同一评分器、IoU 0.5 匹配、球心误差**只在匹配成功的检测上**统计。

| 指标（Dryad-only 臂，conf 0.05 / 0.10） | 结果 |
| --- | --- |
| 球心 ≤50 px 命中 | **4 / 36**（0.05 与 0.10 相同） |
| 有检出帧 | 15/42（0.05）、14/42（0.10） |
| TP / FP / FN | 4 / 33 / 32（0.05）；4 / 28 / 32（0.10） |
| P / R / F1 | 0.1081 / 0.1111 / 0.1096（0.05）；0.1250 / 0.1111 / 0.1176（0.10） |
| AP50（101 点） | 0.0420 |
| 球心中位 / P90（仅命中帧） | 1.46 px / 2.39 px |
| 6 个空帧中的误检 | 2 框 / 1 帧（0.05）；0 框（0.10） |
| 推理耗时 | .pt（GPU）0.34 s/帧；ONNX（CPU）0.59 s/帧 |

**目标（≥28/36）未达成，且低于现有 YOLO 的 15/36。**

### 4.1 为什么"验证集 mAP50 0.80"却在真实域只剩 4/36

1. **AP 与阈值解耦**：mAP 是阈值无关的排序指标。Dryad 微调后模型的**置信度整体塌陷**，
   排序仍能拿到 AP，但任何可用阈值（0.05–0.25）下都几乎不出框。这正是不许只看 mAP 的原因。
2. **灾难性遗忘**：V1 的 521 个 BNDSTT 域伪标签帧在 Dryad 里**没有对应物**；用 5 轮、
   lr 0.005 微调后，模型在目标域的置信度从"能出框"退化到"几乎不出框"。
   诊断证据（非测试帧，12 张）：V1 的最大置信度均值 0.170（12/12 ≥0.05），
   Dryad 臂仅 0.015（0/12 ≥0.05）。
3. **域差异**：Dryad 多为转播/近景（球 15–24 px、常带模糊拉长），BNDSTT 是球馆远景
   （球 25–67 px、高光形态不同）。本轮数据把模型拉向 Dryad 的观感。

### 4.2 评测工具链发现（影响后续复现）

用 ultralytics `.pt` 推理与 ONNX 推理对**同一权重**打分不一致：V1 在 `.pt` 路径只有 7/36，
而 ONNX 路径 15/36（同一图同一权重，`.pt` 的首位框落在别处、分数仅 0.06，ONNX 首位是 0.179 的真球）。
因此**本轮结论一律以 ONNX 版评分器为准**（与历史 15/36、28/36 同口径），
`.pt` 差异已记录为待查的工具链问题（`rect` 取值已排除）。

---

## 5. 交付判定

| 约束 | 状态 |
| --- | --- |
| 未达标前不替换正式模型 | ✅ BallTrack 仍是唯一正式 ball 来源 |
| 不修改 V2.4 交付包 | ✅ ZIP 未改动（哈希 `7edf80ed…`） |
| 不合并 ball/hand/racket、不动手部模型 | ✅ 只训练了单类球模型 |
| 不推送 main、不改 B 侧接口 | ✅ 未推送、未改接口 |
| 未通过验收不导出交付 ONNX | ✅ 只有评测用途的 `dryad_eval_only/*.onnx` |
| 数据/大文件不入库 | ✅ Dryad 原始包、视频、数据集、权重均在 `artifacts/`（gitignored） |

---

## 6. 剩余问题与下一步

1. **不要再用"整包替换"的方式微调**：应把 Dryad 作为**增量数据**混入 V1 数据集
   （保留 521 个 BNDSTT 伪标签帧），或采用"Dryad 预训练 → BNDSTT 伪标签微调"两段式，
   以避免本轮观察到的灾难性遗忘。
2. **置信度校准需要单独指标**：今后每轮都报告"固定阈值下的命中/误检"，mAP 只作参考。
3. **BlurBall 的收益不明显**，但它提供了模糊长度/方向标注；若要做模糊感知的回归头，
   应直接使用其 CSV 中的模糊参数，而不是只当普通框用。
4. **数据量仍偏小**：Dryad 标了 16,090 个球框，本轮只按 stride 3 取了约 4.5k。
   下一轮可全量使用（约 1.6 万帧），但需先解决"混入而非替换"的问题。
5. 未完成的对照：**从 COCO 通用权重训练的对照组**（时间/显存预算内未跑）。

---

## 7. 复现命令

```powershell
# 1) 下载（Dryad 整版 + Zenodo 视频；直连很慢，走代理断点续传）
Invoke-WebRequest -Uri 'https://datadryad.org/api/v2/versions/439548/download' -OutFile artifacts\files\datasets\dryad_tt\dryad_v3_all.zip
curl.exe -L --proxy http://127.0.0.1:7890 -C - -o artifacts\files\datasets\dryad_tt\videos.zip `
  'https://zenodo.org/api/records/19874312/files/Zoutianjian/Videos-For-Sport-Ball-Detection-Dataset-Videos-v0.zip/content'

# 2) 标签审计 + 数据集构建
.\.venv\c-detector\Scripts\python.exe tmp\audit_dryad_labels.py
.\.venv\c-detector\Scripts\python.exe tmp\build_dryad_ball2.py
.\.venv\c-detector\Scripts\python.exe tmp\materialise_dryad_arms.py

# 3) 训练两臂（warm start 自 V1，1280，5 轮）
#    （见 artifacts\runs\train_dryad_noblur.log / train_dryad_all.log 的完整命令行）

# 4) 冻结测试（先导出评测用 ONNX，再用统一评分器）
D:\Python\python.exe -c "..."   # 见 §4 的 dryad_eval_only 导出
.\.venv\c-detector\Scripts\python.exe tmp\eval_ball_onepass.py `
  --onnx artifacts\files\models\dryad_eval_only\dryad_noblur_1280.onnx `
  --dataset bndstt --mode full --tag dryad_noblur_onnx_bndstt
```

评测记录：`artifacts/files/reports/BALL_YOLO_V2/onepass_dryad_noblur_onnx_bndstt.json`、
`artifacts/files/reports/DRYAD_AUDIT/{label_audit.json,bndstt_dryad_noblur.json,bndstt_v1_pt_control.json}`。
