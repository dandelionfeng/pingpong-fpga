# MODEL CARD — unified 3-class ping-pong detector (v2, EXPERIMENTAL)

## 基本信息
- 名称: pingpong_yolov8n_gray_3cls_v2_960
- 架构: YOLOv8n (Ultralytics 8.2.82), 3 类检测头
- 输入: [1,3,960,960] float32 (Gray8 -> Gray3 -> letterbox -> /255)
- 输出: [1,7,18900] = 4 box + 3 class scores, 无 NMS
- 类别: 0=ball, 1=hand, 2=racket (固定, 不可更改顺序)
- 文件: pingpong_yolov8n_gray_3cls_v2_960.onnx, 12,161,114 B

## 训练数据
- 来源: artifacts/files/datasets/pingpong_3cls_v2 (tabletennis ball+racket, bodyhands hand,
  hand_pseudo, hand_synthetic, 负样本), 抽取平衡子集
- train: 3,910 图 / ball 1,978 框 / hand 3,123 框 / racket 4,790 框
- val  : 509 图 / ball 100 框 / hand 1,172 框 / racket 176 框
- 类别映射: 三源统一到 0/1/2, 标签逐字节沿用, 未新造标签
- 划分: tabletennis 按比赛 (M1-M4 train / M5 val), bodyhands 按视频 id, 无帧级泄漏

## 训练配置
- 初始化: artifacts/runs/pingpong_3cls_v1/weights/best.pt (同为 3 类, 兼容)
- epochs 15 (设定 15), imgsz 960, batch 12, AdamW lr0 3e-4, cos_lr, lrf 0.01
- mosaic 0.3 (close_mosaic 5), scale 0.4, degrees 5, fliplr 0.5, hsv_h/s 0, hsv_v 0.4
- seed 42, deterministic, workers 4, AMP, RTX 4060 Laptop 8.6 GB
- 实际耗时 0.471 h (28 min), best epoch 14

## 指标 (val, 非独立测试集)
| class | GT | P | R | AP50 | AP50-95 |
|---|---|---|---|---|---|
| ball | 100 | 0.684 | 0.475 | 0.519 | 0.161 |
| hand | 1172 | 0.666 | 0.557 | 0.613 | 0.290 |
| racket | 176 | 0.726 | 0.679 | 0.735 | 0.354 |
| overall | 1448 | 0.692 | 0.571 | 0.623 | 0.268 |

## 限制
- ball 召回 0.475, 明显弱于专项 ball 模型
- 源数据标签不完整(单类别数据集未标其他类), 训练时会被当作背景
- 无独立测试集, 无 OV9281 真实域验证, 无 RKNN/板端证据
- 仅 EXPERIMENTAL, 未通过正式验收
