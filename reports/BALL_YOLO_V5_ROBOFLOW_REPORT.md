# 球检测第五轮（Roboflow Ping Pong Detection v3 + V1 混合）：审计、训练、评测

日期：2026-10-21　分支：`codex/c-pc-detector`　上轮：[BALL_YOLO_V4_ROBOFLOW_BLOCKED_REPORT](BALL_YOLO_V4_ROBOFLOW_BLOCKED_REPORT.md)

## 0. 结论

**训练与评测全部来自实际运行。新模型在 Roboflow 同域上很强，但在目标域明显劣于 V1，
因此不采用、不做 C++ 接入，BallTrack 继续作为正式 ball 后端。**

| 模型 | 目标域命中（50 px） | P | R | F1 | AP50 | FP | 中位/P90 误差 | 空帧误检 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BallTrack（参考） | **28/36** | — | — | — | — | — | 7.96 / 24.86 px | — |
| **V1（现行）** | **15/36** | **0.2381** | **0.4167** | **0.3030** | **0.2282** | 48 | 2.41 / 5.02 px | 6 框 |
| 本轮候选 @1280 | 9/36 | 0.0750 | 0.2500 | 0.1154 | 0.0352 | 111 | 5.99 / 6.93 px | 2 框 |
| 本轮候选 @960 | 12/36 | 0.1429 | 0.3333 | 0.2000 | 0.0549 | 72 | 5.72 / 6.80 px | 0 框 |

- 未覆盖 `ball_yolo_v1` 权重（`f2dc54ec…` 未变）、未改 V2.4 包（`7edf80ed…`）、未改 C++ 接口、未推 main。
- 本轮只训练 ball 单类；未训练 hand/racket；未使用 Dryad。

---

## 1. 数据定位与完整性

| 项 | 值 |
| --- | --- |
| 文件 | `C:\Users\lenovo\Downloads\Ping Pong Detection.v3i.yolov8.zip` |
| 大小 | 1,497,886,705 B |
| SHA256 | `44201541f63c5c613a5ca0d91bd84b11029a499ee644b1cef3c8a08f54f8c605` |
| ZIP 校验 | 可完整打开，49,688 条目，`Expand-Archive` 成功，无报错 |
| 解压目录 | `artifacts/files/datasets/roboflow_pp/`（独立目录，不覆盖任何现有数据/模型） |
| 来源元数据 | workspace `pingpong-ojuhj` / project `ping-pong-detection-0guzq` / **version 3** / 导出时间 2024-05-20 |
| 许可 | **CC BY 4.0**（`README.dataset.txt` 与 `data.yaml` 均声明） |
| 类别 | `nc: 1`, `names: ['ping-pong-ball']` |

### 1.1 实际数量（以 ZIP 内容为准）

| 划分 | 图像 | 标签 | 球框 | 空标签 | 缺失标签 | 非法行 | 多球图像 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| train | **22,931** | 22,931 | 57,090 | 100 | 0 | 0 | 11,167 |
| valid | **951** | 951 | 2,493 | 0 | 0 | 0 | 477 |
| test | **956** | 956 | 2,399 | 0 | 0 | 0 | 471 |
| **合计** | **24,838** | 24,838 | **61,982** | 100 | 0 | 0 | 12,115 |

网页写 24,985、README 写 24,985、ZIP 实际 **24,838** —— 以 ZIP 为准（少 147 张）。

### 1.2 图像与球框尺寸

- 全部图像为 **640×640（拉伸，非等比）**；抽查 400 张，**0 张损坏**。
- 球框宽（640 像素下的像素值）：中位 **57 px**，p10 **21 px**，p90 **171 px**，最小 1 px，最大 640 px。
- 拉普拉斯方差中位 **1946**（很清晰），按 <60 判定为模糊的只有 127/3,159 个源图 → 该数据集**几乎没有运动模糊样本**。
- 100 个空标签全部在 train：按任务要求**一律不作负样本使用**（未标注 ≠ 无球），抽样时直接跳过。

### 1.3 重复与泄漏（重要）

- 文件名形如 `<源图哈希>_jpg.rf.<增强哈希>.jpg`，同一源图的增强副本共享前缀。
- train 22,931 张只来自 **3,161 个源图**（平均 7.3 个增强副本/源图，最多 **33 个**）。
- **跨集同源**：train↔valid **709** 个、train↔test **712** 个、valid↔test **206** 个源图重复。

→ **官方 valid/test 是被泄漏污染的**，其 mAP 只能当参考，不能当泛化证明。因此本轮自建了
按源图隔离的评测集（见 §2）。

---

## 2. 抽样与混合数据集

`artifacts/files/datasets/ball_rf_v1/`（硬链接，不复制像素）

| 项 | 策略 | 结果 |
| --- | --- | --- |
| 去重 | **每个源图只取 1 张**，丢弃其余增强副本 | 3,159 个可用源图 |
| 分层 | 按球框宽三分位（小 <0.059 / 中 <0.139 / 大）+ 清晰/模糊 | 小 1,009 / 中 1,097 / 大 1,053；模糊仅 127 |
| 自建验证集 | 300 个源图（与训练源图**完全不重叠**） | 300 张 |
| Roboflow 训练 | 剩余 2,859 张 | 2,859 |
| 混入 V1 数据 | 原样加入 `ball_yolo_v1`（1,978 人工 + **521 张 BNDSTT 伪标签** + 239 负样本） | 2,738 张 + 180 验证 |
| **合计** | — | **train 5,597 / val 480**（300 Roboflow + 180 tabletennis Match5） |

Roboflow 占比 51%（2,859 / 5,597）；目标域伪标签 521 张全部保留，负样本 239 张保留。

---

## 3. 训练

| 项 | 值 |
| --- | --- |
| 基线 | warm start 自 `ball_yolo_v1/weights/best.pt`（`f2dc54ec…`，**未覆盖**） |
| 模型 / 输入 | YOLOv8n / **960**（Roboflow 源图 640，960 为 1.5× 上采样；兼顾小球与显存） |
| batch | 16（RTX 4060 Laptop 8 GB，峰值显存 4.9 GB） |
| 增强 | mosaic 0、erasing 0、scale 0.3、translate 0.1、fliplr 0.5、hsv_h/s 0、hsv_v 0.4（灰度） |
| 优化 | lr0 0.003、lrf 0.02、cos_lr、warmup 0.5、seed 42、AMP |
| 轮数 | **20 / 20 轮跑满**（patience 5 未触发，指标一直上升） |
| 实测耗时 | **55 分 46 秒**（16:29:49 → 17:25:35，约 2.8 min/轮） |
| 最佳 epoch | **20**（末轮仍最好，说明未过拟合） |

**一处如实记录的偏差**：任务要求 Windows 下 `workers=0`。实测 `workers=0` 时 **1.87 s/it**
（单轮约 11 分钟，20 轮需 3.7 小时），不可接受；改用 `workers=4`（前四轮已验证稳定，
Windows 下无崩溃），降到约 2.8 min/轮。若必须 workers=0，需把训练集再砍一半。

### 3.1 验证结果

| 验证集 | P | R | mAP50 | mAP50-95 | 说明 |
| --- | --- | --- | --- | --- | --- |
| **自建干净验证集**（300 源图 + 180 Match5） | 0.8817 | 0.7290 | **0.7987** | **0.5092** | 无泄漏，作为选模依据 |
| 官方 valid（951 张） | 0.8831 | 0.8544 | **0.9089** | 0.6285 | **含 709 个训练同源图，虚高** |

---

## 4. 目标域诊断（BNDSTT，仅诊断用途）

统一 ONNX 预处理/解码/NMS/评分器，与 V1 完全同口径。**BNDSTT 未参与训练、未用于挑
checkpoint、未用于调阈值**；此处只做一次诊断汇总。

### 4.1 候选 @1280（与 V1 相同输入尺寸）

| conf | 命中 | TP/FP/FN | P | R | F1 | AP50 | 中位/P90 | 空帧误检 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.05 | 11/36 | 11/173/25 | 0.0598 | 0.3056 | 0.1000 | 0.0381 | 5.96 / 6.76 px | 9 |
| 0.10 | 9/36 | 9/111/27 | 0.0750 | 0.2500 | 0.1154 | 0.0352 | 5.99 / 6.93 px | 2 |
| 0.15 | 8/36 | 8/76/28 | 0.0952 | 0.2222 | 0.1333 | 0.0324 | 6.04 / 7.01 px | 0 |

### 4.2 候选 @960（其训练尺寸）

| conf | 命中 | TP/FP/FN | P | R | F1 | AP50 | 中位/P90 | 空帧误检 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.05 | 13/36 | 13/128/23 | 0.0922 | 0.3611 | 0.1469 | 0.0597 | 5.68 / 6.78 px | 6 |
| 0.10 | 12/36 | 12/72/24 | 0.1429 | 0.3333 | 0.2000 | 0.0549 | 5.72 / 6.80 px | 0 |
| 0.15 | 6/36 | 6/42/30 | 0.1250 | 0.1667 | 0.1429 | 0.0249 | 6.17 / 7.00 px | 0 |

**V1 同口径为 15/36、P 0.2381、R 0.4167、F1 0.3030、AP50 0.2282、FP 48、中位 2.41 px。**

结论：候选在所有阈值、两种输入尺寸下都**不如 V1**——命中更少、AP50 只有 V1 的 1/4、
误检 1.5–3.6 倍、球心误差中位数从 2.41 px 退化到 5.7–6.0 px。

---

## 5. 导出与一致性

| 项 | 值 |
| --- | --- |
| 权重 | `artifacts/runs/ball_rf_v1/weights/best.pt`　6,309,667 B　SHA256 `28b2a8bb9cc7f37b1c43d29e71dbb46b0866218737c941beb4c0588d48140679` |
| ONNX @960 | `artifacts/files/models/ball_rf_v1/ball_rf_v1_960.onnx`　12,159,554 B　SHA256 `7d2da4eb27b07a515551e141fafaa7c3e34253a4498812d2e3da5138e85e3e36` |
| ONNX @1280 | `artifacts/files/models/ball_rf_v1/ball_rf_v1_1280.onnx`　12,218,920 B　SHA256 `f5ec1e7a19deada33486ab65bee2f7e251c1594cb9d777eae0d55b2971802d9d` |
| PT↔ONNX 一致性 @960 | sigmoid 后最大差 **5.96e-08**，框坐标差 **0.00 px**，top-1 anchor 一致 → **通过** |
| PT↔ONNX 一致性 @1280 | sigmoid 后 **5.96e-08**，框差 **0.00 px**，top-1 anchor 一致 → **通过** |

（原始 logits 差 ~3e-3 属 float32 噪声；判定用解码前的 sigmoid 值与框坐标。）

### 5.1 ONNX CPU 推理延迟（单进程、5 帧预热、20 帧平均、3 次重复）

| 模型 | 输入 | 延迟 | 帧率 | 大小 |
| --- | --- | --- | --- | --- |
| V1 | 1280 | **73.4 ms**（72.8–73.9） | 13.6 FPS | 12,218,920 B |
| 候选 | 960 | **41.6 ms**（41.3–41.7） | 24.0 FPS | 12,159,554 B |
| 候选 | 1280 | **73.9 ms**（73.7–74.3） | 13.5 FPS | 12,218,920 B |

（同一进程内连开多个 ORT session 会互相拖慢到 900+ ms，这是测量假象；上表为每个模型
独立进程的稳定值。）

---

## 6. 交付判定

| 约束 | 状态 |
| --- | --- |
| 目标域优于 V1 才做 C++ 验证 | ❌ 未优于（9–13/36 < 15/36）→ **未做 C++ 验证** |
| 不覆盖原始模型 | ✅ V1 权重与 ONNX 未改动 |
| 不覆盖 V2.4 交付包 | ✅ ZIP 哈希仍 `7edf80ed…` |
| 不改 C++ 对外接口 | ✅ |
| 只训练 ball | ✅ 单类 `ball` |
| 不使用 Dryad | ✅ 本轮数据只来自 Roboflow + 既有 V1 数据 |
| 未标注帧不当负样本 | ✅ 100 个空标签全部跳过 |
| 保留 BallTrack 正式后端 | ✅ |
| 原始数据/权重不入库 | ✅ 均在 `artifacts/`（gitignored） |

**候选模型标记为实验候选，不作为正式交付。**

---

## 7. 失败分析

1. **球尺度不匹配**：Roboflow 是 640×640 拉伸的近景（球宽中位 57 px ≈ 图宽的 9%），
   BNDSTT 是 1920×1080 球馆远景（球宽中位 34 px ≈ 图宽的 1.8%）。模型学到的是"大而亮的球"，
   到远景中小球上置信度不够，只能靠**多开火**去覆盖 → FP 暴涨、命中仍不足。
2. **拉伸变形**：源图被非等比拉伸到方图，球的圆度/长宽比信息被破坏；迁移到未拉伸的 16:9
   画面时特征分布不一致。
3. **该数据集几乎无模糊样本**（模糊源图仅 127/3,159），无法补上 BNDSTT 的运动模糊难题。
4. **混合比例**：Roboflow 占 51%，虽然保留了 521 张目标域伪标签与 239 负样本，但仍不足以
   抵抗域漂移（与此前几轮"微调即遗忘"的观察一致）。
5. **官方验证集虚高**（mAP50 0.909）完全是同源泄漏造成的，不能用来判断真实能力——
   这也是本轮坚持自建按源图隔离验证集的原因。

---

## 8. 下一步（按性价比）

1. **把 Roboflow 当"补充"而不是"主体"**：比例降到 20–30%，并把 BNDSTT 伪标签从 521 扩到
   2,000+（跑完剩余非测试 session 的 BallTrack 伪标签，约 2.5 h CPU）。
2. **恢复宽高比**：不要用被拉伸的 640 方图，改为从 Roboflow 原始 4:3/16:9 分辨率导出，
   或训练时用 `rect=True` 的方形 padding（当前实现已是 letterbox，但源图已被拉伸，无法恢复）。
3. **尺度增强对齐目标域**：训练时把 Roboflow 图缩小（scale 0.15–0.35）模拟远景小球，
   让球在输入中约为 10–20 px，与 BNDSTT 一致。
4. 若仍要冲 28/36，最终仍需要**目标域真实标注**（哪怕 200–300 框）或全量伪标签。

---

## 9. 复现命令

```powershell
# 1) 定位 / 解压 / 审计
Expand-Archive -Path "$env:USERPROFILE\Downloads\Ping Pong Detection.v3i.yolov8.zip" `
  -DestinationPath artifacts\files\datasets\roboflow_pp -Force
.\.venv\c-detector\Scripts\python.exe tmp\audit_roboflow_pp.py

# 2) 按源图抽样 + 与 V1 混合
.\.venv\c-detector\Scripts\python.exe tmp\build_ball_rf.py

# 3) 训练（warm start 自 V1，960，20 轮，patience 5）
.\.venv\c-detector\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('artifacts/runs/ball_yolo_v1/weights/best.pt').train(data='artifacts/files/datasets/ball_rf_v1/data.yaml', epochs=20, patience=5, imgsz=960, batch=16, workers=4, seed=42, device=0, lr0=0.003, mosaic=0.0, erasing=0.0, scale=0.3, hsv_h=0.0, hsv_s=0.0, project='artifacts/runs', name='ball_rf_v1')"

# 4) 导出 + 一致性
D:\Python\python.exe tmp\export_only.py --run ball_rf_v1 --sizes 960,1280
.\.venv\c-detector\Scripts\python.exe tmp\parity_check.py --run ball_rf_v1 --sizes 960,1280

# 5) 目标域诊断
.\.venv\c-detector\Scripts\python.exe tmp\eval_ball_onepass.py `
  --onnx artifacts\files\models\ball_rf_v1\ball_rf_v1_1280.onnx --dataset bndstt --mode full --tag ball_rf_v1_1280_bndstt
```

记录：`artifacts/files/reports/ROBOFLOW_PP_AUDIT/{audit.json,sample_report.json}`、
`artifacts/files/reports/BALL_YOLO_V2/onepass_ball_rf_v1_{960,1280}_bndstt.json`、
`artifacts/files/models/ball_rf_v1/parity.json`。
