# MODEL CARD — unified 3-class V3 (EXPERIMENTAL)

## 基本信息
- 名称: pingpong_yolov8n_gray_3cls_v3_960
- 架构: YOLOv8n, 3 类检测头, 单次前向输出 ball/hand/racket
- 输入: [1,3,960,960] float32 (Gray8 -> Gray3 -> letterbox 114 -> /255)
- 输出: [1,7,18900] = 4 box + 3 class scores, 图内无 NMS
- 类别: 0=ball, 1=hand, 2=racket (固定)
- 文件: pingpong_yolov8n_gray_3cls_v3_960.onnx, 12,161,114 B
- SHA256: b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba

## 训练数据 (PINGPONG_UNIFIED_3CLS_V4)
- train 4,431 图 / ball 2,499 / hand 3,698 / racket 4,790
- val      509 图 / ball 100  / hand 1,172 / racket 176   (与 V2 同一个 val)
- 相对 V2 新增: 521 张 BNDSTT 真实域球帧 (+521 ball, +575 自动 hand 候选)
- 未新增: racket 标注 (自动补标注该域不可靠)
- 划分: tabletennis 按比赛 M1-M4/M5, bodyhands 按视频 id, 新增帧只进 train

## 训练配置
- 初始化: artifacts/runs/pingpong_3cls_v1/weights/best.pt (3 类, 兼容)
- epochs 16 (设定) -> 实际 15, imgsz 960, batch 12, AdamW lr0 3e-4, cos_lr, lrf 0.01
- mosaic 0.2 (close 5), scale 0.4, degrees 5, fliplr 0.5, hsv_h/s 0, hsv_v 0.4
- seed 42, deterministic, AMP, RTX 4060 Laptop 8.6 GB
- 耗时 0.533 h (32 min), best epoch 9

## 指标 (val 509, 非独立测试集)
| class | P | R | AP50 | AP50-95 |
|---|---|---|---|---|
| ball | 0.827 | 0.460 | 0.538 | 0.154 |
| hand | 0.679 | 0.538 | 0.607 | 0.285 |
| racket | 0.734 | 0.727 | 0.738 | 0.347 |
| overall | 0.746 | 0.575 | 0.627 | 0.262 |

conf=0.25 时: ball P 0.904 / R 0.470 / F1 0.618; hand 0.691/0.558/0.618; racket 0.760/0.756/0.758

## 与 V2 的差异 (同 val)
- ball: P +0.143, AP50 +0.019, F1@0.25 +0.057, R -0.015
- hand: AP50 -0.006, F1@0.25 -0.008 (基本持平)
- racket: R +0.048, F1@0.25 +0.044, AP50 +0.003
- overall mAP50 +0.005, mAP50-95 -0.006

## 限制
- 无独立测试集; 无 OV9281 真实域验证; RKNN/NPU 与板端未做; C++ 未实测
- ball recall 0.46 仍然偏低
- 新增球帧缺 racket 标注; 575 个 hand 框是自动候选, 未经人工确认
- 标记 EXPERIMENTAL, 未通过正式验收
