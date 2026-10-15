# THIRD PARTY NOTICES — C 端感知联调包

本包包含或依赖以下第三方成果。**AGPL-3.0 没有被隐藏**。

---

## 1. RacketVision / BallTrack

| 项 | 值 |
| --- | --- |
| 来源 | https://github.com/OrcustD/RacketVision |
| 论文 | RacketVision: A Multiple Racket Sports Benchmark for Unified Ball and Racket Analysis（AAAI 2026 Oral） |
| **License** | **MIT** |
| 用途 | `models/balltrack_tracknetv3.onnx` 是官方 `balltrack_best.pth`（TrackNetV3）导出的 ONNX |
| 是否重训 | **否**。使用官方 pretrained checkpoint，本项目从未训练或 fine-tune |
| 权重来源 | HuggingFace `linfeng302/RacketVision-Models` → `checkpoints/balltrack_best.pth` |
| 备注 | 官方模型代码为**原文使用**；本仓库仅提供 mmengine API-compatible shim（不影响任何张量） |

---

## 2. Ultralytics（YOLOv8）

| 项 | 值 |
| --- | --- |
| 来源 | https://github.com/ultralytics/ultralytics |
| **License** | **AGPL-3.0** |
| 用途 | 训练框架；`hand` 与 `racket` 两个检测器均为 YOLOv8n |
| 版本 | 8.2.82 |
| 备注 | **AGPL-3.0 是强 copyleft 许可**。若本包或其衍生物需要以非 AGPL 方式分发，需先与 Ultralytics 确认商业许可。使用前请自行确认与比赛/项目要求的兼容性 |

---

## 3. hand-keypoints dataset

| 项 | 值 |
| --- | --- |
| 来源 | https://github.com/ultralytics/assets/releases/download/v0.0.0/hand-keypoints.zip |
| 文档 | https://docs.ultralytics.com/datasets/pose/hand-keypoints |
| **License** | **AGPL-3.0**（Ultralytics 发布；上游为 CMU Panoptic hand keypoints 数据） |
| 用途 | 训练 `hand` 检测器的唯一数据来源 |
| 规模 | 26,768 图（train 18,776 / val 7,992），1 类 `hand`，21 关键点 |
| **bbox 来源** | **数据集自带的 bbox 字段（标签第 1..4 列）**。**未从关键点推导** |
| 处理 | 图像统一转 gray3；标签仅保留 bbox 字段，关键点已丢弃。原始 zip 只读，未修改 |
| SHA256 | `8f383934dd6f63b04795f2b055151ba10552709c45adf043d47eea05d9cbf99f` |

---

## 4. ONNX Runtime

| 项 | 值 |
| --- | --- |
| 来源 | https://github.com/microsoft/onnxruntime |
| **License** | **MIT** |
| 版本 | 1.20.1（Windows x64 CPU build） |
| 用途 | C++ 推理后端 |
| 随包分发 | `bin/onnxruntime.dll` |

---

## 5. OpenCV

| 项 | 值 |
| --- | --- |
| 来源 | https://github.com/opencv/opencv |
| **License** | **Apache-2.0** |
| 版本 | 4.10.0（官方 Windows package） |
| 用途 | 图像预处理、letterbox、连通域解码、视频读写、overlay 绘制 |
| 随包分发 | `bin/opencv_world4100.dll`、`bin/opencv_videoio_ffmpeg4100_64.dll` |
| 备注 | `opencv_videoio_ffmpeg4100_64.dll` 内含 FFmpeg 组件，其许可见 OpenCV 发行说明 |

---

## 6. nlohmann/json（仅构建桥接时需要）

| 项 | 值 |
| --- | --- |
| 来源 | https://github.com/nlohmann/json |
| **License** | **MIT** |
| 版本 | 3.11.3（single header） |
| 用途 | 仅 `DetectorBackend` 桥接编译时需要；**不随本包分发** |

---

## 7. 未包含的内容

- **pose / wrist 模型**：`yolov8n-pose.pt` **不作为本包 runtime 必需文件**。
  Pose 状态为 OPTIONAL / LEGACY DIAGNOSTIC。
- 训练数据、训练 run、原始视频、人工标注：**均未包含**。
- RKNN toolkit：**未包含、未使用**。

---

## 8. 使用建议

如果本包要用于**非开源**的竞赛或产品交付，请注意：

1. `ball`（BallTrack）是 **MIT**，可自由使用；
2. `hand` 与 `racket` 检测器、以及它们使用的训练框架与数据涉及 **AGPL-3.0**；
3. 请在使用/分发前确认许可兼容性，必要时联系相关方获取替代许可。
