# 第三方声明 / Third-party notices

本包内的四个 ONNX 权重是**本项目自己训练**的模型（以 Ultralytics YOLOv8n 为骨干），
不是第三方发布的预训练权重。本文件记录它们所依赖的第三方组件与数据来源。

## 1. Ultralytics YOLOv8（AGPL-3.0）

- 训练与导出使用 [Ultralytics](https://github.com/ultralytics/ultralytics) YOLOv8n（本项目环境为 8.2.x）。
- Ultralytics 代码与由它导出的模型适用 **AGPL-3.0**。若对外分发本包中的 ONNX，
  需同时遵守 AGPL-3.0 的义务（提供对应源代码、保留版权与许可声明）。
- 商用前请确认团队对 AGPL 的接受度；本项目目前为校内竞赛/研究用途。

## 2. Roboflow "Ping Pong Detection" v3（CC BY 4.0）

- 链接：https://universe.roboflow.com/pingpong-ojuhj/ping-pong-detection-0guzq （version 3）
- 许可：**CC BY 4.0**（`README.dataset.txt` 与 `data.yaml` 内声明）
- 用途：`ball_roboflow_960`、`ball_roboflow_1280`、`ball_v6_round2` 三个模型的辅助训练数据。
- 义务：**署名**。对外发布基于上述模型的结果或再分发模型时，应注明数据来源与 CC BY 4.0。
- 该数据集的图像本身**不包含在本交付包内**（原始压缩包在项目 `artifacts/` 下，未入 Git）。

## 3. 本项目的 tabletennis 数据

- 来源：项目早期 Roboflow `tabletennis-nbcdc` v2（CC BY 4.0）与自建 BNDSTT 采集。
- 用途：`ball_yolo_v1_1280` 的主要训练数据。

## 4. BNDSTT 冻结测试集（本项目内部人工标注）

- 42 张图（1920×1080）、36 个球框、6 个空帧；标注为人工复核（`MANUAL_REVIEWED`）。
- 仅用于项目内部评测；打包进本 ZIP 是为了让队长用**同一份 GT** 复现评分。
- 若对外发布，请先确认比赛/采集方的授权范围。

## 5. OpenCV / ONNX Runtime

- 推理工具依赖 OpenCV（Apache-2.0）与 ONNX Runtime（MIT）。
- 二者为**运行时依赖**，未打包进本 ZIP，由使用者的 Python 环境提供。

## 6. 未包含的第三方内容

- 未包含任何 Roboflow 原始数据集压缩包、训练日志、伪标签、视频、PT 权重或缓存。
- 未包含任何未经授权的外部开源权重（此前评测过的三个公开模型未进入本包）。
