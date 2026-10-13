# MODEL MANIFEST — C 端感知模型交接清单

冻结日期：2026-10-13。给 A 同学做板端部署用。

> **所有权重文件都不进 Git**（`.pt` / `.onnx` / `.rknn` 均被 `.gitignore` 忽略）。
> 本文件是**清单引用**，实际文件在 `artifacts/` 下。

## 1. 正式模型总表

| 用途 | 模型 | 本地路径 | SHA256 | 输入 | 输出 | 框架 | 导出状态 | RKNN 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **ball（最终）** | BallTrack (TrackNetV3, 官方 pretrained) | `artifacts/files/models/balltrack/balltrack_best.pth` | `00d707b9db7a49561c411e4765956e79bcd7c7e20c7a0a535073440b3e972342` | `[1,15,288,512]` | `[1,1,288,512]` heatmap | PyTorch 2.5.1 | **ONNX READY** | FP16 待做 |
| **racket** | YOLOv8n ball+racket | `artifacts/files/models/ball_racket_yolov8n_v1/best.pt` | `8d1b65e3d424701ba9eead6501325ba322f71258fd0e66cc065f21098d78c7b4` | `[1,3,640,640]` | `[1,6,8400]` | Ultralytics 8.2.82 | **ONNX READY** | FP16 待做 |
| **ball（fallback）** | 同上（同一权重里的 ball 输出） | 同上 | `8d1b65e3d424701ba9eead6501325ba322f71258fd0e66cc065f21098d78c7b4` | 同上 | 同上 | 同上 | 同上 | 同上 |
| **wrist** | yolov8n-pose (COCO 预训练) | `artifacts/files/models/ultralytics/yolov8n-pose.pt` | `c6fa93dd1ee4a2c18c900a45c1d864a1c6f7aba75d84f91648a30b7fb641d212` | `[1,3,640,640]` | `[1,56,8400]` | Ultralytics 8.2.82 | **ONNX READY** | FP16 待做 |

文件大小：BallTrack 44.4 MB；YOLO ball+racket 6.0 MB；pose 6.5 MB。

## 2. 每个模型的详细契约

### 2.1 BallTrack（ball 主方案）

| 项 | 值 |
| --- | --- |
| 来源 | 官方 `https://github.com/OrcustD/RacketVision`（AAAI 2026 Oral 论文官方实现） |
| 许可 | **MIT** |
| checkpoint 来源 | HuggingFace `linfeng302/RacketVision-Models`，文件 `checkpoints/balltrack_best.pth` |
| 是否训练过 | **NO — 只使用官方 pretrained，本项目从未训练或 fine-tune** |
| 架构 | TrackNetV3（encoder-decoder U-Net） |
| seq_len | 4 |
| 输入分辨率 | 512 × 288 |
| 输入通道 | 15 = 3 × (seq_len 4 + 1 median background)，`bg_mode=concat` |
| last_only | true（输出只保留最后一帧热图） |

**预处理（必须严格按此，来自官方 `inference.py`）**：

```text
1. 每帧 resize 到 (512, 288)，/255 -> float32
2. median 背景 resize 到 (512, 288)，/255，作为一个 frame 放在序列最前
3. 取 center frame 之前的 4 帧：index = center-4, center-3, center-2, center-1（负数按官方 clip 到 0）
4. 拼成 (15, 288, 512) = concat(median, 4 frames)
5. 前向 -> heatmap (1, 288, 512)
6. 解码：threshold=0.5 -> 二值化 -> cv2.findContours(RETR_EXTERNAL) -> 取面积最大的 boundingRect
   confidence = 该矩形内热图均值
7. center = (x + w/2) * (orig_w/512), (y + h/2) * (orig_h/288) -> 原图坐标
8. cx == 0 and cy == 0 视为未检测到（Visibility = 0）
```

**依赖 median 背景**：官方 dataset 不提供 `median.npz`，必须自己算 ——
对同一 source clip 的**全部帧取逐像素中位数**（官方 `create_median.py` 语义）。
本项目实测 clip 内背景基本静止，用 clip 内中位数与整场中位数差异有限，但**这是一处已知偏差**。

**阈值**：`heatmap_threshold = 0.5`（官方默认，**未调优**）。

### 2.2 YOLOv8n ball+racket（racket 主方案 + ball fallback）

| 项 | 值 |
| --- | --- |
| 训练数据 | 公开 `tabletennis_ball_racket_v1`（Roboflow `yolo-class-delww/tabletennis-nbcdc` v2，CC BY 4.0） |
| 规模 | 1480 = train 1036 / val 291 / test 153 |
| 类别 | `0 ball`，`1 racket` |
| 训练配置 | yolov8n，imgsz 640，120 epochs（best 102），batch 16，seed 42，patience 25 |
| 输出 | `[1, 6, 8400]` = 4 box(cx,cy,w,h) + ball score + racket score |
| 阈值 | `base_conf = 0.02` 推理；**racket_conf = 0.30**；ball fallback `ball_conf = 0.05` |
| 预处理 | letterbox 640，BGR→RGB，/255（Ultralytics 标准） |

### 2.3 yolov8n-pose（wrist）

| 项 | 值 |
| --- | --- |
| 是否训练 | **NO — 公开 COCO 预训练权重，本项目不训练、不标 hand** |
| 输出 | `[1, 56, 8400]` = 4 box + 1 person conf + 17 × 3 keypoint (x, y, conf) |
| 关键点索引（Python 0-based） | **left_wrist = 9，right_wrist = 10** |
| 阈值 | person conf 0.25；wrist `valid = conf >= 0.30` |
| 低置信处理 | `valid = false` 且 `xy = null`，**绝不伪造坐标** |

## 3. ONNX 导出状态

| 模型 | ONNX 文件 | 大小 | parity (max abs diff) | 判定 |
| --- | --- | --- | --- | --- |
| YOLO ball+racket | `ball_racket_yolov8n_v1.onnx` | 12,117,766 B | 1.709e-03 | **PASS** |
| pose | `yolov8n_pose.onnx` | 13,345,830 B | 2.045e-03 | **PASS** |
| BallTrack | `balltrack_tracknetv3.onnx` | 45,330,200 B | 4.917e-07 | **PASS** |

位置：`artifacts/files/reports/ONNX_EXPORT_V1/models/`（**不进 Git**）。
详细报告：`artifacts/files/reports/ONNX_EXPORT_V1/ONNX_PARITY_REPORT.md`。

⚠️ **导出环境版本差异**：ONNX 在 ultralytics **8.4.176** 环境导出，而 c-detector 是 **8.2.82**。
在同一批 BNDSTT 人工 GT 帧上，ONNX 检出 14/36 而 c-detector 检出 16/36（2 帧边界差异）。
**ONNX 图本身对其源 PyTorch 是数值等价的**；跨版本差异需在 8.2.82 环境重新导出才能消除。

## 4. RKNN 状态

**RKNN_PREPARED_NOT_EXECUTED**

| 项 | 值 |
| --- | --- |
| Toolkit2 可用 | **NO**（本机未安装；PyPI 镜像无此包） |
| 目标平台 | `rk3576` |
| 已交付 | `export_rknn.py`、`calibration_manifest.txt`、`RKNN_DEPLOYMENT_GUIDE.md` |
| FP16 | 未执行 |
| INT8 | 未执行 |
| 板端验证 | **NO — 没有 AFH03 真机** |

## 5. 禁止事项

- 不得把 `.pt` / `.onnx` / `.rknn` 提交 Git；
- 不得在没有真机的情况下声称 BOARD VERIFIED；
- 不得使用 `BNDSTT_MANUAL_GT_V1` 训练任何模型（**只读评测**）；
- 不得重新开启 hand / toss_hand / racket_hand 路线。
