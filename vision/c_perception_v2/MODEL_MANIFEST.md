# MODEL MANIFEST — C 端感知模型交接清单（HANDOFF V2）

更新日期：2026-10-15。给 A 同学做板端部署、给队长本机调用。

> **所有权重文件都不进 Git**（`.pt` / `.onnx` / `.rknn` / `.exe` / `.dll` 均被 `.gitignore` 忽略）。
> 本文件是**清单引用**。可直接运行的模型 + exe 打包在
> `artifacts/handoff/C_PERCEPTION_HANDOFF_V2.zip`。

## 1. 正式模型总表

| 用途 | 模型 | 本地路径 | 输入 | 输出 | 输入格式 | 阈值 | C++ 支持 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **ball（最终）** | BallTrack (TrackNetV3, 官方 pretrained) | `artifacts/files/models/balltrack/balltrack_best.pth` | `[1,15,288,512]` | `[1,1,288,512]` | **gray3**（median+4帧） | heatmap 0.5 | ✅ |
| **hand** | YOLOv8n 1 类 hand bbox | `artifacts/files/models/hand_yolov8n_gray_v1/best.pt` | `[1,3,640,640]` | `[1,5,8400]` | **gray3** | 0.25 | ✅ |
| **racket** | YOLOv8n ball+racket（gray3 适配） | `artifacts/files/models/ball_racket_yolov8n_gray3_v1/best.pt` | `[1,3,640,640]` | `[1,6,8400]` | **gray3** | 0.30 | ✅ |
| ball（fallback） | 同上 racket 模型的 ball 类 | — | — | — | gray3 | 0.05 | ✅ |
| **pose/wrist** | yolov8n-pose | `artifacts/files/models/ultralytics/yolov8n-pose.pt` | `[1,3,640,640]` | `[1,56,8400]` | gray3 | 0.25 | **OPTIONAL** |

**Pose 状态：OPTIONAL / LEGACY DIAGNOSTIC。** 正式 ball / hand / racket 输出必须在**完全不运行 Pose** 的情况下成立。

## 2. 每个模型的详细契约

### 2.1 BallTrack（ball 主方案）

| 项 | 值 |
| --- | --- |
| 来源 | 官方 `https://github.com/OrcustD/RacketVision`（AAAI 2026 Oral） |
| 许可 | **MIT** |
| checkpoint | HF `linfeng302/RacketVision-Models` → `checkpoints/balltrack_best.pth` |
| 是否训练过 | **NO — 只使用官方 pretrained** |
| 架构 | TrackNetV3，`seq_len=4`，`bg_mode=concat`，`last_only=True` |
| 输入分辨率 | 512 × 288 |
| 15 通道构成 | `median(3ch) + f(i-4)(3ch) + f(i-3)(3ch) + f(i-2)(3ch) + f(i-1)(3ch)` |
| 输出 | 单张热图 `[1,1,288,512]`（`last_only=True` 裁掉其余 3 张） |
| 解码 | 阈值 0.5 → `findContours(RETR_EXTERNAL)` → 最大外接矩形 → 矩形内均值作 confidence |
| 坐标 | `center × (orig_w/512, orig_h/288)` → 原图坐标 |

**gray3 正确做法**：上面 5 个组成部分**每一个都是不同的灰度帧复制成 3 通道**，
不是"某一帧复制 15 次"。

**背景帧（重要偏差）**：官方 Python 参考实现用**整段视频的逐像素中位数**。
C++ 在线引擎**把第一帧冻结为背景**。
原因：逐帧中位数在 1920×1080 上约 1 秒/次刷新，远超模型本身耗时。
三脚架固定机位下背景静止，首帧即可代表背景。
**这是与官方实现的有记录偏差，相机移动时必须重新评估。**

### 2.2 Hand（1 类 bbox detector）

| 项 | 值 |
| --- | --- |
| 数据 | Ultralytics 官方 **hand-keypoints**，`hand-keypoints.zip` |
| 数据许可 | **AGPL-3.0**（Ultralytics 发布；上游为 CMU Panoptic hand keypoints） |
| 规模 | 26,768 图 / 26,768 标签（train 18,776 + val 7,992） |
| **bbox 来源** | **数据集自带的 bbox 字段（标签第 1..4 列）**，**不是**从 21 个关键点推导 |
| 关键点 | 已丢弃（本阶段只要 bbox） |
| 类 | `0 = hand`（单类；不区分 toss/racket/left/right） |
| 输入 | gray3（BGR→GRAY8→复制 3 通道），标签坐标不变 |
| 配方 | yolov8n, imgsz 640, epochs 100, patience 20, batch 16, seed 42, device 0, amp |

## 3. ONNX 导出状态

| 模型 | ONNX 文件 | 大小 | parity（对同环境 PyTorch） |
| --- | --- | --- | --- |
| ball | `balltrack_tracknetv3.onnx` | 45,330,200 B | PASS（max abs 4.917e-07） |
| hand | `hand_yolov8n_gray.onnx` | 12,116,986 B | 结构正确 |
| racket | `racket_yolov8n.onnx` | 12,117,766 B | 结构正确 |

位置：`artifacts/handoff/C_PERCEPTION_HANDOFF_V2/models/`（**不进 Git**）。

⚠️ ONNX 在 ultralytics **8.4.176** 环境导出，c-detector 是 **8.2.82**；
在 BNDSTT 人工 GT 帧上曾有 2 帧边界差异。**ONNX 图对其源 PyTorch 数值等价**。

## 4. C++ 运行时契约

| 项 | 值 |
| --- | --- |
| 源码 | `software/pc_pipeline/modules/c_actual/` |
| 输入 | **`CV_8UC1` GRAY8**（引擎内部做 gray3 / letterbox / normalize） |
| 输出 | ball（state/center/region/confidence）+ hands[] + rackets[]，**原图坐标** |
| 后端 | ONNX Runtime 1.20.1（CPU 可用；CUDA 可选） |
| 编译器 | MSVC 19.44（VS 2022） |
| 构建 | CMake + Ninja，`CMakeLists.txt` 已交付 |

## 5. RKNN 状态

**RKNN_PREPARED_NOT_EXECUTED** —— 本机无 rknn-toolkit2，无 AFH03 真机。
见 `RKNN_DEPLOYMENT_GUIDE.md`。**BOARD VERIFIED = NO**。

## 6. 禁止事项

- 不得把 `.pt` / `.onnx` / `.rknn` / `.exe` / `.dll` / `.zip` 提交 Git；
- 不得在没有真机的情况下声称 BOARD VERIFIED；
- 不得使用 `BNDSTT_MANUAL_GT_V1` 训练任何模型（**只读评测**）；
- **不得用 wrist 周围固定方框冒充 hand bbox**（hand 必须是真实 YOLO 输出）；
- 不得让 C 判断 hand 角色（toss / racket），这属于 B。
