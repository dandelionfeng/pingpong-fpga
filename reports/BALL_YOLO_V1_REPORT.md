# 乒乓球 YOLO 球检测器（BALL_YOLO_V1）：训练与独立验收

日期：2026-10-20　分支：`codex/c-pc-detector`　基线交付：[V2.4 统一三类](C_UNIFIED_3CLS_V24.md)

## 0. 结论先行

**未达到验收目标。** 冻结一次后在 `BNDSTT_MANUAL_GT_V1` 上：

| 指标 | 本次 YOLO（1280，conf 0.10） | BallTrack 灰度基线（参考值） | 判定 |
| --- | --- | --- | --- |
| 球心误差 ≤50 px 命中 | **15 / 36（41.7%）** | 28 / 36（77.8%） | **未达标** |
| 检出帧 | 30 / 42 | 28 / 36 | — |
| Precision / Recall / F1 | 0.2381 / 0.4167 / 0.3030 | — | — |
| AP50 | 0.2282 | — | — |
| 球心误差中位数 | **2.41 px** | 7.96 px | **更好** |
| 球心误差 P90 | **5.02 px** | 24.86 px | **更好** |

结论：**YOLO 定位更准（中位 2.4 px vs 8.0 px），但找球能力明显更差（15/36 vs 28/36）**。
按验收标准（达到或超过 BallTrack）判定为**未通过**，因此：

- 不接入正式 C++ 接口（BallTrack 仍是唯一 ball 来源，冻结契约未动）；
- 不覆盖 V2.4 交付包与 Release；
- 现有稳定交付物保持原样。

---

## 1. 数据审计

| 项 | 事实 |
| --- | --- |
| 「844 个真实球框」 | = `tabletennis_ball_racket_gray3_v1` **train** 分区的 ball 框（844）。另有 val 233、test 125 |
| 球尺寸（1920 宽等效） | tabletennis 各场中位 19–31 px；BNDSTT 人工 GT 中位 34.3 px（24.7–66.8） |
| 独立测试集 | `BNDSTT_MANUAL_GT_V1`：42 图，**36 个 ball 框**（36 图有球、6 图无球），5 个 session |
| `BNDSTT_YOLO_MVP_V1`（29 个 curated 包） | **不可用于训练**：优先用 sha256 反查来源失败（图片被重编码），改用缩略图匹配后，**能判定归属的 2 帧全部来自测试 session `20240503_163810`**。整包排除，记录在 `artifacts/files/reports/BALL_AUDIT/curated_session_join.json` |
| `BNDSTT_MVP_v1` 280 帧 | 标签为空（`annotation_state: empty YOLO label files`），无人工球框 |
| 视频 session | 33 个；5 个测试 session 从伪标签/背景/训练中全程排除 |

**标注正确性已目视核对**（`artifacts/files/reports/BALL_YOLO_V1/label_check_sheet.jpg`）：
tabletennis 人工框与伪标签框内都能看到球；负样本帧确实无球。所以本轮的低指标**不是标签错误**导致的。

---

## 2. 训练数据：BALL_YOLO_V1

| 组成 | 图数 | 球框 | 性质 |
| --- | --- | --- | --- |
| tabletennis Match1–4（×2 过采样） | 1978 | 1978 | 人工 |
| 同上的无球帧 + Match7 | 232 | 0 | 负样本 |
| BallTrack 伪标签（10 个非测试 session） | **521** | 521 | **伪标签（非人工）** |
| 伪标签负样本 | 7 | 0 | 负样本 |
| **train 合计** | **2738** | **2499** | |
| val（tabletennis **Match5**，按比赛留出） | 180 | 100 | 人工 |
| holdout（Match6，未使用） | 115 | 113 | 人工 |

- 分组：tabletennis **按比赛**切分（V1 的 train/val/test 都来自同一批 7 场比赛，属近似重复泄漏；本轮不用它做验收）。
- 伪标签来源：BallTrack 在**非测试**视频上输出，过滤条件（先定后跑）：`conf ≥ 0.45`、热图连通域尺寸 6–120 px、面积 40–9000、**前后 2 帧内 40 px 时序一致**；框取**实测热图连通域**，不是固定 N×N 假框。
- 二次质检：伪标签框必须比周围亮（`mean_in − mean_ring ≥ 8`），**675 → 521，剔除 154（23%）**。
- train/val 完全相同图像交集 = **0**。

---

## 3. 训练

GPU：RTX 4060 Laptop（8 GB），torch 2.5.1+cu121，ultralytics 8.2.82，`yolov8n.pt` 初始化。

| 轮次 | 配置 | 结果 | 判定 |
| --- | --- | --- | --- |
| 第 1 次（3 轮到即停） | imgsz 1280, batch 8, mosaic **1.0** | mAP50 0.04–0.05 | **失败**：mosaic 把 1920 宽切到 ~640 子图，球只剩 5–8 px |
| 第 2 次（正式） | imgsz 1280, batch 8, lr0 0.01, cos_lr, **mosaic 0**, erasing 0, scale 0.3, hsv_h/s=0 | 10 轮后早停（patience 8） | mAP50 **0.1157**（第 2 轮最优），耗时 1274 s |

正式训练的最佳权重：`artifacts/runs/ball_yolo_v1/weights/best.pt`
SHA256 `f2dc54ec618ebb1f3dc8f8ef6d24022bd06a68850dd9cc2e0ed207ce2adb131e`。

选 checkpoint 用的是 **Match5 验证集**，测试集从未参与。

---

## 4. 验证集表现（Match5，人工框，仅用于选型/选阈值）

| conf | presence | TP | FP | P | R | hit≤50px |
| --- | --- | --- | --- | --- | --- | --- |
| 0.05 | 162/180 | 30 | 295 | 0.092 | 0.300 | 30/100 |
| **0.10（选中）** | 100/180 | 24 | 88 | 0.214 | 0.240 | 24/100 |
| 0.15 | 53/180 | 17 | 34 | 0.333 | 0.170 | 17/100 |
| 0.25（交付默认） | 13/180 | 5 | 4 | 0.556 | 0.050 | 5/100 |

训练集自身命中率 **87%（26/30）**，Match5 只有 **33%**——**跨比赛域差距**是主要瓶颈，不是拟合不足。
在验证集上，无论取哪个阈值都远达不到可用水平，因此没有再消耗测试集。

---

## 5. 正式独立测试（冻结后仅此一次）

命令（阈值 0.10 由 Match5 选出，测试集不参与选择）：

```
python tmp/eval_ball_bndstt.py --onnx artifacts/files/models/ball_yolo_v1/ball_yolov8n_gray_1280.onnx \
    --dataset bndstt --conf 0.10 --tag yolo1280_bndstt_final
```

| 指标 | 值 |
| --- | --- |
| 图 / 有球图 / 空图 | 42 / 36 / 6 |
| 有检出的帧 | 30 / 42（71.4%） |
| TP / FP / FN | **15 / 48 / 21** |
| Precision / Recall / F1 | **0.2381 / 0.4167 / 0.3030** |
| AP50（101 点） | **0.2282** |
| 球心误差中位数 / P90 | **2.41 px / 5.02 px**（仅在命中的 15 帧上） |
| 球心误差 ≤50 px | **15 / 36（41.7%）** |
| 空帧误检 | 6 个框，来自 3 帧（6 帧空图中有 3 帧误报） |

与 BallTrack 基线（28/36 命中、中位 7.96 px、P90 24.86 px）相比：**命中数只有基线的一半**，
但一旦命中，定位精度是基线的 3 倍以上。

### 同一评分器下重跑 BallTrack 的结果（含口径说明）

用同一套 `tmp/eval_ball_bndstt.py` 重建 BallTrack 的 5 帧滑窗（背景取片段首帧）复算：
presence 24/42、TP 7、命中 7/36、中位 6.97 px、P90 7.88 px。

**这不能当作基线**：42 帧里有 **6 帧 `frame_index < 5`**，滑窗不足 5 帧时 BallTrack 必然 WARMUP，
这 6 帧被算成漏检；原基线（28/36）的实现细节（片段起点、背景来源）无法完全复原。
因此**正式比较以上一节的参考值为准**，本次复算只用于说明"同一评分器下两者的相对形态"。

---

## 6. 失败分析（如实）

1. **训练数据太少**：仅 989 个人工球框（4 场比赛）+ 521 个伪标签框。BallTrack 是在大规模视频上训练的时序模型，
   单帧检测器在这个数据量下很难追平。
2. **跨比赛域差距大**：同一伪标签/人工框体系下，训练集命中 87%，未见比赛 Match5 只有 33%。
   不同比赛的光照、机位、球速差异显著。
3. **小目标分辨率不足**：1920×1080 经 1280 letterbox 后球只有 13–21 px（P3 特征图上约 1.6–2.6 格）。
   用同一权重在 1920 输入上推理反而更差（M5：presence 57/180、TP 1），说明不是简单提高推理分辨率能解决。
4. **置信度偏低**：命中时球心误差只有 2.4 px，说明定位分支学得不错；但未见域上分数普遍落在 0.05–0.15，
   排序能力（AP）差，任何阈值都无法同时拿到召回和精度。
5. **伪标签量不足**：BallTrack 在 CPU 上 190 ms/帧，13% 的帧才有球；本轮只跑到 10 个 session 的 521 个可用框，
   没有把非测试视频（还有 18 个 session）全部挖完。

---

## 7. 速度（CPU，1280）

| 检测器 | 单帧耗时 | 说明 |
| --- | --- | --- |
| 本 YOLO（ONNX，1280） | **72.4 ms/帧（13.8 FPS）** | 含 letterbox + 推理 + 解码，ORT 默认线程 |
| BallTrack（ONNX，512×288×15） | 190 ms/帧 | 仅模型推理；C++ 引擎整帧 1.2–1.9 s（含 YOLO 与后处理） |

即：**单帧检测器有 2.6× 以上的速度优势**，这也是继续做下去的主要价值；
但当前精度不达标，速度优势不足以支撑替换。

---

## 8. 产物与哈希

| 文件 | 大小 | SHA256 |
| --- | --- | --- |
| `artifacts/runs/ball_yolo_v1/weights/best.pt` | — | `f2dc54ec618ebb1f3dc8f8ef6d24022bd06a68850dd9cc2e0ed207ce2adb131e` |
| `artifacts/files/models/ball_yolo_v1/ball_yolov8n_gray_1280.onnx` | 12,218,920 B | `185a337ec9ed6c52e867c3748e889ef8fac56c855ce5cceb478a7213a1f4a17b` |
| `artifacts/files/models/ball_yolo_v1/ball_yolov8n_gray_1920.onnx` | 12,388,040 B | `c40a3c887e65e3ac64517224869c44e51eaf013293e7fc28d26bd7d7ead7b537` |

数据与评测记录：

- `artifacts/files/datasets/ball_yolo_v1/`（build_report.json、data.yaml、holdout/）
- `artifacts/files/datasets/ball_pseudo_v1/build_report.json`（伪标签协议与过滤条件）
- `artifacts/files/reports/BALL_YOLO_V1/`：`test_yolo1280_bndstt_final.json`（正式测试）、
  `test_yolo1280_m5_c*.json`（验证集扫描）、`latency.json`、`overlay_*.jpg`、`label_check_sheet.jpg`
- `artifacts/files/reports/BALL_AUDIT/curated_session_join.json`（curated 包被测试 session 污染的证据）

**未做**：C++ 接入与 Python↔C++ 一致性（按约定只有达标才做）、RKNN 转换、上板。
**未改动**：`C_PERCEPTION_CAPTAIN_INTEGRATION_V2_4` 包、V2.4 Release、C++ 源码与冻结接口。

---

## 9. 下一步（按性价比）

1. **人工球标注优先**：当前 989 个人工框是根本瓶颈。补 3000–5000 个真实域人工球框（不同 session），
   比任何训练技巧都有效。
2. **把伪标签挖完**：剩余 18 个非测试 session 全量跑 BallTrack（约 190 ms/帧），预计还能得到 2000+ 框；
   注意伪标签只能提升域适应性，不能替代人工真值。
3. **裁剪/平铺高分辨率训练**：以 960×960 裁剪训练（球在输入中的相对尺寸翻倍），推理用 2×2 平铺后融合，
   可望把召回从 0.42 拉到 0.6+；代价是 C++ 侧要加平铺预处理。
4. **时序融合**：单帧 YOLO + 3–5 帧轨迹一致性（类似 BallTrack 的后处理），可以把误检压下去，
   但召回仍受单帧能力限制。
5. 达标线（沿用本次验收）：BNDSTT 命中 ≥28/36、中位误差 ≤7.96 px、P90 ≤24.86 px，且空帧误检不高于基线。
