# C 端感知 — FINAL HANDOFF V1

收口日期：2026-10-13　分支：`codex/c-pc-detector`

> 本报告是 C 同学 PC 算法与部署准备的正式收口说明。
> **未训练任何新模型；未使用任何人工标注做训练；未修改 quick_test。**

---

## A. Final architecture

```text
BALL      : official RacketVision BallTrack (TrackNetV3, pretrained, READ-ONLY)
            + causal Kalman association (continuity only)
RACKET    : YOLOv8n ball+racket detector (public tableTennis v2, this repo)
WRISTS    : yolov8n-pose.pt (COCO pretrained, NOT trained)
            left_wrist = index 9, right_wrist = index 10
TEMPORAL  : causal Kalman, max_prediction_gap = 2, no future frames
```

C **不判断发球合法与否**；role association / release / apex / contact / 3D trajectory /
legal judgement 全部属于 B 模块。

关键不变式：

1. `PREDICTED_ONLY` **不是** detection；
2. `RECOVERED_LOW_CONF` 必须拥有真实 detector candidate；
3. **不伪造 hand bbox**（wrist 是关键点，不是 box）；
4. 所有坐标 = **original eye image coordinates**；
5. association 只能是 `HEURISTIC` / `UNKNOWN`。

详见 `vision/c_perception_v2/FINAL_ARCHITECTURE.md`。

## B. Ball detector decision

**FINAL BALL = BALLTRACK**（官方 RacketVision pretrained）。

评测集：`BNDSTT_MANUAL_GT_V1` 中 `MANUAL_REVIEWED` 且含 ball 框的 **36 帧**（只读，未训练）。
BallTrack 输入为其**原始 source video 的真实连续上下文**（seq_len=4），只在 center frame 计分。

| 指标 | YOLO ball | BallTrack |
| --- | --- | --- |
| detection presence | 16/36 = 0.4444 | **24/36 = 0.6667** |
| 其中 center error ≤ 50 px | 7/36 = 0.1944 | **24/36 = 0.6667** |
| center error median | 561.247 px | **8.088 px** |
| center error P90 | 699.805 px | **28.995 px** |
| center error P95 | 699.805 px | **29.806 px** |

判定依据（方案 §14）：差距 **+22.2 个百分点**，远超 5pp 阈值 → 采用 BallTrack。

**非退化性已验证**：24 个检出中心互不相同（x 跨度 802–1222，y 跨度 240–774），排除常数输出。

**没有报告 precision/FP**：GT 集合只含「有球」的帧，没有人工确认的负样本，按方案要求不伪造。

**fallback**：`ball_racket_yolov8n_v1/best.pt` 的 ball 输出继续保留（`ball.backend = yolo`），
因为 BallTrack 需要额外依赖与 median 背景。

BallTrack 来源：`OrcustD/RacketVision`（AAAI 2026 Oral，**MIT**），checkpoint 来自 HF
`linfeng302/RacketVision-Models`，SHA256 `00d707b9db7a49561c411e4765956e79bcd7c7e20c7a0a535073440b3e972342`，**从未训练或修改**。

## C. Racket detector

YOLOv8n ball+racket（公开 `tabletennis_ball_racket_v1`，1480 张，类 `0 ball / 1 racket`）。

- 权重 SHA256：`8d1b65e3d424701ba9eead6501325ba322f71258fd0e66cc065f21098d78c7b4`
- 公开 test：racket **AP50 = 0.8127**，AP50-95 = 0.3435，P 0.7628 / R 0.7750
- 工作阈值 `racket_conf = 0.30`：P/R/F1 = 0.7897 / 0.7643 / 0.7768

## D. Pose / wrist

`yolov8n-pose.pt`（SHA256 `c6fa93dd1ee4a2c18c900a45c1d864a1c6f7aba75d84f91648a30b7fb641d212`），**公开 COCO 预训练，不训练、不标 hand**。

COCO 17 关键点，Python 0-based：**left_wrist = 9，right_wrist = 10**。
低置信 wrist → `valid = false` 且 `xy = null`，**绝不伪造坐标**。

## E. Temporal

因果 Kalman / association，`max_prediction_gap = 2`，**禁止使用 t+1 / t+2**，算法延迟 **0 帧**。

连续视频诊断集 `BNDSTT_TEMPORAL_DIAGNOSTIC_V1`：8 clips / 8 sessions / 324 连续帧，60 fps，与 BNDSTT_30 source 和 quick_test **零重叠**。

| tracker | detector-supported | RECOVERED_LOW_CONF | PREDICTED_ONLY | track breaks | 最长稳定段 | stable ratio |
| --- | --- | --- | --- | --- | --- | --- |
| SIMPLE3 | 221 | 6 | 0 | 10 | 42 | 0.8305 |
| SIMPLE5 | 223 | 8 | 0 | 10 | 42 | 0.8306 |
| KALMAN | 255 | 8 | 28 | 7 | 44 | 0.8311 |

**Claim limit**：只能说 temporal association **改善了 candidate continuity**、
**recover 了 8 个低置信候选**。**不能声称 recall 提升** —— 没有连续人工 GT。
`PREDICTED_ONLY` 只用于轨迹连续性，不得发送为「detector 确信看到了球」。

## F. Public metrics

公开 `tabletennis_ball_racket_v1` test（153 张，唯一有真 GT 的集）：

| | P | R | AP50 | AP50-95 |
| --- | --- | --- | --- | --- |
| overall | 0.8152 | 0.7022 | **0.7361** | 0.2986 |
| ball | 0.8676 | 0.6293 | **0.6595** | 0.2536 |
| racket | 0.7628 | 0.7750 | **0.8127** | 0.3435 |

固定阈值（IoU 0.50，one-to-one greedy，`base_conf = 0.02`）：

| profile | ball_conf | racket_conf | ball P/R/F1 | racket P/R/F1 |
| --- | --- | --- | --- | --- |
| HIGH_RECALL | 0.03 | 0.05 | 0.4524 / 0.76 / 0.5672 | 0.554 / 0.8429 / 0.6686 |
| **BALANCED（推荐）** | 0.05 | 0.3 | 0.557 / 0.704 / 0.6219 | 0.7897 / 0.7643 / 0.7768 |
| HIGH_PRECISION | 0.25 | 0.4 | 0.8791 / 0.64 / 0.7407 | 0.834 / 0.7357 / 0.7818 |

## G. BNDSTT domain diagnostics

`BNDSTT_30_V1`（30 帧来自 30 个不同 source）—— **只能报 COVERAGE，不能报 recall/precision/AP**：

| profile | ball coverage | racket coverage | both |
| --- | --- | --- | --- |
| HIGH_RECALL | 21/30 | 26/30 | 19/30 |
| **BALANCED（推荐）** | 19/30 | 17/30 | 8/30 |
| HIGH_PRECISION | 12/30 | 13/30 | 5/30 |

时间维度诊断见 E 节（`BNDSTT_TEMPORAL_DIAGNOSTIC_V1`，**不是 accuracy benchmark**）。

## H. Latency

RTX 4060 Laptop，imgsz 640，warmup 20 / 100 iterations：

| 阶段 | mean | median | P95 |
| --- | --- | --- | --- |
| YOLO ball+racket | 38.513 ms | 39.165 ms | 43.632 ms |
| Pose | 44.709 ms | 44.741 ms | 51.212 ms |
| Temporal (Kalman) | 7.818 ms/clip | 7.823 ms/clip（≈0.1956 ms/帧） | 8.697 ms/clip |
| combined serial | — | 83.907 ms | — |

**THEORETICAL ONLY** 异步吞吐 22.4 FPS（detector / pose 分线程无争用的理论值，**未实测**）。

⚠️ BallTrack 的延迟已在 bake-off 中逐帧记录，均值见
`BALL_DETECTOR_FINAL_BAKEOFF/comparison.json` 的 `latency` 字段（未与 YOLO 做同基准对比）。

## I. ONNX status

| 模型 | ONNX 大小 | parity max abs diff | 判定 |
| --- | --- | --- | --- |
| YOLO ball+racket | 12,117,766 B | 1.709e-03 | **PASS** |
| Pose | 13,345,830 B | 2.045e-03 | **PASS** |
| BallTrack | 45,330,200 B | 4.917e-07 | **PASS** |

parity 在 **20 张固定公开 test 图**上完成（atol/rtol 1e-3），报告：
`artifacts/files/reports/ONNX_EXPORT_V1/ONNX_PARITY_REPORT.md`。

⚠️ **已知问题**：导出环境用 ultralytics 8.4.176，而 c-detector 是 8.2.82。
在 36 张 BNDSTT 人工 GT 帧上 ONNX 检出 14/36、c-detector 检出 16/36（2 帧边界差异）。
ONNX 图**对其源 PyTorch 数值等价**；要消除跨版本差异需在 8.2.82 环境重新导出。

## J. RKNN status

**RKNN_PREPARED_NOT_EXECUTED**

- rknn-toolkit2 **未安装**（PyPI 镜像无此包，Rockchip 只在官方 index 发布）；
- 目标平台 `rk3576`；
- 已交付 `export_rknn.py`、`calibration_manifest.txt`、`RKNN_DEPLOYMENT_GUIDE.md`；
- FP16 / INT8 均**未执行**；
- **没有 AFH03 真机 → BOARD VERIFIED = NO**。

## K. Limitations

1. **无连续人工 GT** → temporal 只能做结构性诊断，**不能声称 recall 提升**；
2. **BallTrack 需要 median 背景**：官方 dataset 不提供，本项目按 clip 全帧中位数本地生成，
   与官方「整场中位数」有**已知偏差**；
3. **BallTrack 未做阈值调优**（沿用官方 `thre = 0.5`）；
4. **BNDSTT 域内置信度系统性偏低**，`BNDSTT_30` 只能报 coverage；
5. **人工 GT 无负样本** → ball bake-off 无法报 precision / FP；
6. **ONNX 跨 ultralytics 版本有 2 帧边界差异**（见 I 节）；
7. **RKNN 未转换、未上板**；
8. 相机曝光策略暂不调整 —— 当前 baseline 对已有运动模糊并不敏感；该公开 test 上较低 Laplacian
   sharpness 样本检出率反而更高，但这是**相关性结果**，尚不能推出主动增加曝光或运动拖影会提高
   检测性能，且后续还需考虑球中心定位、双目匹配与轨迹估计误差。

## L. B integration schema

C 输出 `PerceptionResultV2Final`（`vision/c_perception_v2/ball_racket.py`）：

```json
{
  "schema_version": "1",
  "metadata": {"source_pair_id", "task_id", "generation", "timestamp", "frame_id",
                "eye", "original_width", "original_height"},
  "ball": {"source": "balltrack|yolo|none",
           "state": "DETECTED|RECOVERED_LOW_CONF|PREDICTED_ONLY|INVALID",
           "confidence", "bbox_xyxy", "center_xy", "track_id", "detected"},
  "racket": [{"confidence", "bbox_xyxy"}],
  "persons": [{"person_id", "bbox_xyxy", "confidence",
               "left_wrist": {"name", "keypoint_index", "xy", "confidence", "valid", "geometry": "keypoint"},
               "right_wrist": {"name", "keypoint_index", "xy", "confidence", "valid", "geometry": "keypoint"}}],
  "association": {"status": "HEURISTIC|UNKNOWN", "is_ground_truth": false,
                  "candidate_server_person_id", "candidate_racket_wrist",
                  "candidate_toss_wrist", "confidence", "reason"}
}
```

**Legacy 兼容**：`to_legacy_boxes()` 只输出 `ball` 与 `racket`，
**绝不输出 hand**，也不会围绕 wrist 造矩形。wrist 通过 V2 的 `persons[].left/right_wrist` 传出。

## M. A deployment handoff

- 模型清单与 SHA256：`vision/c_perception_v2/MODEL_MANIFEST.md`；
- 推理配置：`vision/c_perception_v2/config/default_inference.yaml`；
- ONNX：`artifacts/files/reports/ONNX_EXPORT_V1/models/`（3 个，parity PASS）；
- RKNN：`vision/c_perception_v2/export_rknn.py` + `RKNN_DEPLOYMENT_GUIDE.md`；
- 相机接口目标 **1280×720 per eye**，但代码**不写死尺寸**（用真实输入或 metadata）；
- 板端待办见 `RKNN_DEPLOYMENT_GUIDE.md` 最后一节。

## N. Reproducibility

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"
& $python -m pytest tests -q                # 93 passed
& $python -m unittest discover -s tests     # 29 tests OK
& $python tools/check_repo.py               # 0 problems
```

环境：Python 3.12.14，torch 2.5.1+cu121，torchvision 0.20.1+cu121，ultralytics 8.2.82，
CUDA 12.1，RTX 4060 Laptop 8 GB。**版本未升级。**

ONNX 导出环境（隔离）：torch 2.14.1+cpu / onnx 1.23.2 / onnxruntime 1.31.0，
位于短路径 `C:\pp_export`（因为仓库路径超长且含中文，触发 Windows MAX_PATH）。

## O. Exact git commit

收口 commit SHA 见最终汇报；本文件与该 commit 一同提交。

---

## 明确未声称的事项

- ❌ 未声称上板通过 / BOARD VERIFIED / RK3576 REAL-TIME VERIFIED；
- ❌ 未声称 temporal recall 提升；
- ❌ 未声称 BNDSTT_30 上的 precision / recall / mAP；
- ❌ 未声称 ball bake-off 的 precision / FP；
- ❌ 未声称旧 hand 路线仍在维护。
