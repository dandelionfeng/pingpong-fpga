# C 端感知 V2 — FINAL ARCHITECTURE（正式冻结）

本文件是 C 同学的正式收口架构。冻结日期：2026-10-13。

## 架构总览

```
BALL      : official RacketVision BallTrack (TrackNetV3, pretrained, READ-ONLY)
            -> ball center (original eye coords) + confidence + visibility
            + causal Kalman association (continuity only)

RACKET    : YOLOv8n ball+racket detector (this repo, trained on tableTennis v2)
            -> racket bbox_xyxy (original eye coords)

WRISTS    : yolov8n-pose.pt (pretrained, NOT trained)
            -> COCO keypoint index 9 = left_wrist, index 10 = right_wrist
            -> low-confidence wrist => valid=false, xy=null (never fabricated)

TEMPORAL  : causal Kalman / association
            states: DETECTED / RECOVERED_LOW_CONF / PREDICTED_ONLY / INVALID
            max_prediction_gap = 2, no future frames
```

随后由 **B** 模块负责：racket-hand / toss-hand role association → release → apex → contact
→ 3D trajectory → toss height → legal / illegal judgement。

> **C 不判断发球合法与否。** C 只提供感知输出（ball / racket / wrist / association candidate）。

## 关键不变式（不可违反）

1. **`PREDICTED_ONLY` != DETECTION**。它是 Kalman 预测，只用于轨迹连续性，
   不得发送为“detector confidently saw the ball”。
2. **`RECOVERED_LOW_CONF` 必须拥有真实 detector candidate**（`base_conf <= conf < working conf`，
   且通过运动 gate）。没有 candidate 的帧只能是 `PREDICTED_ONLY` 或 `INVALID`。
3. **不伪造 hand bbox**。Pose 输出的是手腕**关键点**；禁止围绕 wrist 造一个矩形并称为 hand detector 输出。
4. **所有坐标都是 original eye image coordinates**，不是 640 letterbox 坐标。
   代码不得写死图像尺寸；使用 `context.original_size` 或真实输入尺寸。
5. **association 只能是 HEURISTIC / UNKNOWN**，绝不可伪装成 Ground Truth。
6. **C 不输出最终合法/非法判断。**

## Ball 后端选择依据（FINAL BALL = BALLTRACK）

在 `BNDSTT_MANUAL_GT_V1` 的 36 个含球人工 GT 帧上（只读、无训练）：

| 指标 | YOLO ball | BallTrack |
| --- | --- | --- |
| detection presence | 16/36 (0.444) | **24/36 (0.667)** |
| center error ≤ 50 px | 7/36 (0.194) | **24/36 (0.667)** |
| center error median | 561.2 px | **8.1 px** |
| center error P90 | 699.8 px | **29.0 px** |

差距远大于 5 个百分点阈值，且定位误差低两个数量级 → 采用 BallTrack。
详见 `artifacts/files/reports/BALL_DETECTOR_FINAL_BAKEOFF/summary.md`。

**回退**：`ball_racket_yolov8n_v1/best.pt` 继续保留为已验证的 fallback ball 后端
（`ball.backend = yolo`），因为 BallTrack 需要额外依赖与 median 背景。

## Racket

YOLOv8n ball+racket 模型的 racket 输出。权重：`artifacts/files/models/ball_racket_yolov8n_v1/best.pt`，
SHA256 前缀 `8d1b65e3d424701b`。公开 test：racket AP50 = 0.8127。

## Wrists

`yolov8n-pose.pt` 公开预训练，**不训练、不标 hand**。
COCO 17 关键点，Python 0-based：`index 9 = left_wrist`，`index 10 = right_wrist`。
置信度低于阈值 → `valid = false` 且 `xy = null`，**不造坐标**。

域内表现：BNDSTT_30 上 30/30 帧检出发球员，44/45 人双手腕有效。

## Temporal

因果 Kalman / association，`max_prediction_gap = 2`，**只使用 current 与 past 帧**。
`stable_track_ratio` 定义（分子分母都只含 DETECTED 或 RECOVERED_LOW_CONF 帧，恒 ≤ 1）：

```
sum(len(every maximal run of >= 5 consecutive DETECTED-or-RECOVERED_LOW_CONF frames))
------------------------------------------------------------------------------------
                            detector_supported_frames
```

连续视频诊断（`BNDSTT_TEMPORAL_DIAGNOSTIC_V1`，8 clips / 324 连续帧）实测：

| tracker | detector-supported | recovered | predicted-only | track breaks | longest segment | stable ratio |
| --- | --- | --- | --- | --- | --- | --- |
| RAW (no track) | - | - | - | - | - | - |
| SIMPLE causal 3 | 221 | 6 | 0 | 10 | 33 | 0.8305 |
| SIMPLE causal 5 | 223 | 8 | 0 | 10 | 33 | 0.8306 |
| **KALMAN** | **255** | **8** | 28 | **7** | **44** | **0.8311** |

**Claim limit**：只能声称 temporal association 改善了 candidate continuity 并 recover 了 8 个低置信候选；
**不能声称 recall 提升**——没有连续人工 GT。

## 坐标契约

- 检测器输出、Pose 关键点、融合结果**一律使用 original eye image coordinates**；
- 相机接口目标是 **1280×720 per eye**，但**代码不写死**：所有函数从真实输入或
  `metadata.original_width / original_height` 取值；
- Ultralytics `Results.boxes.xyxy` 已映射回原图，直接使用；不做二次缩放。

## 相关数据集角色（不要混用）

| 数据集 | 帧结构 | 用途 | 允许的指标 |
| --- | --- | --- | --- |
| `BNDSTT_30_V1` | 30 帧来自 30 个不同 source，**非连续** | 单帧 domain detection **coverage** | coverage / candidate count |
| `BNDSTT_TEMPORAL_DIAGNOSTIC_V1` | 8 段段内真正相邻的连续帧 | temporal candidate association **diagnostic** | continuity / dropout / track break |
| `tabletennis_ball_racket_v1` | 公开 v2，1480 张带 GT | 训练与 test 指标 | P / R / mAP |

## 部署准备

- ONNX：见 `artifacts/files/reports/ONNX_EXPORT_V1/ONNX_PARITY_REPORT.md`；
- RKNN：见 `vision/c_perception_v2/RKNN_DEPLOYMENT_GUIDE.md`；
- 模型清单：见 `vision/c_perception_v2/MODEL_MANIFEST.md`。
