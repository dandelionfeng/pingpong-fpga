# 球拍 YOLO V3 训练轮 · 执行摘要

日期：2026-10-24　分支：`codex/c-pc-detector`
详细报告：`artifacts/racket_yolo_v3/RACKET_V3_FINAL_REPORT.md`

## 结论

用现有数据训练了两个 V3 变体，**都没有超过 V2b**，因此**不替换部署件**（旧 640 ONNX 保持不变）。
工程目标（P≥0.90 / R≥0.90 / AP50≥0.90 / AP50-95≥0.55）未达成。

## 数据

- 唯一训练数据：`RACKET_TARGET_V2`（`artifacts/racket_yolo_v2/dataset/RACKET_TARGET_V2/`）
- train 1,055 图 / 2,395 球拍框（Match1–4）；val 180 / 176（Match5）；test 115 / 182（Match6）
- **无帧级泄漏**（按比赛划分）；旧部署模型是在泄漏划分上训练的，其数字不可作泛化
- `pingpong_3cls_v2` 实测去重后只有 1,055 帧、全在 V2 内 → **没有新数据可加**

## 两轮训练（都从 V2b 权重续训）

| 变体 | 配置 | 实际轮数 | 耗时 | 最佳 | 结果 |
| --- | --- | --- | --- | --- | --- |
| V3-1280 | 1280 / AdamW 3e-4 / mosaic 0 / scale 0.35 | 17（设定 40，主动停止） | ~15 min | ep8 | mAP50 0.359（明显退化） |
| **V3-960** | 960 / AdamW 2e-4 / mosaic 0 / scale 0.35 | 17（设定 60，early stop） | **10.5 min** | ep1 | mAP50 0.4572 / mAP50-95 0.1863 |

GPU：RTX 4060 Laptop 8.6 GB，CUDA 可用。

## 四模型对比（同一数据、同一匹配规则、阈值在 val 选）

| 模型 | val AP50 | val@0.20 P/R/F1 | test AP50 | test@0.20 P/R/F1 |
| --- | --- | --- | --- | --- |
| Old 640（部署） | **0.675** ⚠泄漏 | 0.908/0.671/**0.771** | 0.898 | 0.904/0.879/0.891 |
| V2 960 | 0.555 | 0.783/0.614/0.688 | 0.884 | 0.802/0.868/0.834 |
| **V2b 960** | 0.562 | 0.803/0.671/0.731 | **0.920** | 0.857/0.890/0.873 |
| V3 960（本轮） | 0.549 | 0.864/0.648/**0.740** | 0.904 | 0.845/**0.901**/0.872 |

**最好的是 V2b（test AP50 0.920）**；V3 只在 recall 和 val-F1 上略好，val AP50 更低。

## 模型文件

| 文件 | SHA256 |
| --- | --- |
| `artifacts/runs/racket_v3_960/weights/best.pt` | `01c66bd79f837b24037c35ea2b4ba36e7a21ae691a73ffab4f9c826ca6b32f16` |
| `artifacts/files/models/racket_v3_960/racket_v3_960_960.onnx` | `18c2dc5e56552808928e30359b8e8717d4bf0ecf2ee4b46d02d6e8ab5ad0cc72` |
| 部署件（未改）`racket_yolov8n_gray.onnx` | `e606e8deb7151da87ac86412810e74db199ee7d8de2a59bef425f0bc0e8703f7` |

ONNX 可加载、`[1,3,960,960]→[1,6,18900]`、类别 0=ball/1=racket、实际推理跑通；
V3 的 PT/ONNX parity **未单独跑**（未进入交付流程），V2b 的 parity 已通过。

## 保护与 Git

- 未改 C++（改动文件数 0）、未改 Ball/Hand、未动 V2.x 交付包（`7edf80ed…` 未变）
- 未推送、未改 main；本地提交本摘要
