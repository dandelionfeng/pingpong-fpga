# MODEL_CARD — V3 三分类（RKNN 部署用）

| 项 | 值 |
|---|---|
| 名称 | pingpong_yolov8n_gray_3cls_v3_960 |
| 架构 | YOLOv8n，3 类检测头，单次前向 |
| 输入 | [1,3,960,960] float32（GRAY8 → Gray3 → letterbox 114 → /255） |
| 输出 | [1,7,18900]（4 框 + 3 类分数，图内无 NMS） |
| 类别 | 0=ball 1=hand 2=racket（固定） |
| 原交付 ONNX | sha256 b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba（6 输出，未改动） |
| 转换用 ONNX | sha256 39a9eb3a62da2d58373291747b7a740dc6d652ea8f2c850d77509aeae3b2301e（单输出，精度一致） |
| 训练 | YOLOv8n 960，4,431 图，15/16 epoch，best 9，32 min，RTX 4060 |
| 训练数据 | pingpong_unified_3cls_v4（train 4,431 / val 509） |

## PC 端实测精度（val 509 图，历史开发验证集，非独立测试集）

| 类别 | P | R | F1 | AP50 |
|---|---:|---:|---:|---:|
| Ball | 0.823 | 0.510 | 0.630 | 0.492 |
| Hand | 0.691 | 0.558 | 0.618 | 0.504 |
| Racket | 0.760 | 0.756 | 0.758 | 0.689 |

阈值：ball 0.20 / hand 0.25 / racket 0.25。

## 限制
- 无真实 OV9281 验证、无 RKNN、无板端、无 C++ 编译验证
- 640 分辨率实测不可用（ball R 0.050）
- 标签完整性有已知缺口（tabletennis 帧无 hand 标注等）
