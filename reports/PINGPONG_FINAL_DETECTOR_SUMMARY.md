# 最终检测器方案 · 执行摘要（MODE A 采用，MODE B 否决）

日期：2026-10-27　分支：`codex/c-pc-detector`　起点：`0720fda`
交付包：`artifacts/handoff/PINGPONG_FINAL_DETECTOR_FOR_CAPTAIN.zip`

## 结论

**采用 MODE A（单个 V3 三分类 YOLO）**。MODE B（ball_v6 + V3 双模型）在本项目数据上
**Ball 指标崩溃**（F1 0.025、409 张无球帧里 180 张误报），且延迟翻倍 → 否决。

## 1. 两种模式的真实实现

| | MODE A `unified_v3` | MODE B `dual_yolo` |
| --- | --- | --- |
| 模型数 | 1（V3） | 2（ball_v6 + V3） |
| Ball 来源 | V3 的 class 0 | ball_v6（V3 的 ball 输出被**显式丢弃**） |
| Hand/Racket | V3 class 1/2 | V3 class 1/2 |
| 每帧前向 | 1 | 2 |

统一入口 `unified_detector.py --backend unified_v3|dual_yolo`，两种模式**输出同一数据结构**
（`class_id` / `confidence` / `bbox_xyxy` / `bbox_xywh`，单位原图像素，xywh 用左上角约定）。

## 2. 公平精度评测（同一 509 张 val，阈值 0.20/0.25/0.25 冻结）

| 指标 | A ball | B ball | A hand | B hand | A racket | B racket |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TP / FP / FN | **51/11/49** | 6/367/94 | 654/292/518 | 654/292/518 | 133/42/43 | 133/42/43 |
| Precision | **0.8226** | 0.0161 | 0.6913 | 0.6913 | 0.7600 | 0.7600 |
| Recall | **0.5100** | 0.0600 | 0.5580 | 0.5580 | 0.7557 | 0.7557 |
| F1 | **0.6296** | 0.0254 | 0.6176 | 0.6176 | 0.7578 | 0.7578 |
| AP50 | **0.4921** | 0.0046 | 0.5042 | 0.5042 | 0.6890 | 0.6890 |
| 无球帧误报 | **0/409** | 180/409（44%） | — | — | — | — |

**双 YOLO 的 Ball 不是"略差"，是完全不可用**：`ball_v6_round2` 在 BNDSTT 近景域训练，
本项目 val 是 1920×1080 全台视角，域不匹配。

## 3. 性能（CPU，ONNX Runtime 1.31.0）

| 后端 | 初始化 | Mean | Median | P95 | FPS | RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **unified_v3** | **48.8 ms** | **208.0 ms** | 207.0 | 228.3 | **4.81** | 566 MB |
| dual_yolo | 576.2 ms | 811.6 ms | 846.5 | 940.7 | 1.23 | 701 MB |

⚠ **测量时 QAE+QPINN Case II 训练在跑（未干预）**，系统 CPU 46–51%，绝对毫秒被显著抬高
（同机 18.6% 负载时 unified_v3 曾测得 46 ms）。可信的是比例：双模型 ≈ 2× 单模型计算量。
后处理（解码+NMS）仅 **3.9 ms**，不是瓶颈。

**无 GPU 加速**：本机 ORT 只有 `AzureExecutionProvider` + `CPUExecutionProvider`，**无 CUDA EP**。

## 4. 推理加速措施（已实装）

Session 单次创建并复用；预分配输入张量与 letterbox 画布；Gray3 原地广播写入；
`ORT_ENABLE_ALL`；线程可调（8 线程比 4 线程快 31%）；单次 `argmax` 解码 + 类内 NMS；
双模型共享同一帧输入。

## 5. C++ 集成

**本轮未修改任何 C++ 文件，也未编译**（本机无 cmake/cl/g++）。

已核对现有实现（只读）：
- `yolo_detector_onnx.cpp` 从 `out_shape[1] - 4` **自动推导类别数** → 天然支持 3 类；
- `perception_engine.cpp` 对 hand/racket 分别套阈值，且**故意丢弃 ball 类**（ball 唯一来源是 BallTrack）。

因此推荐 **A1 零代码改动**：只替换 ONNX，并把 `racket_conf` 从 0.30 调到 **0.25**。
若要启用统一模型的 ball 输出（A2），属于**接口变更**，需 B 模块复核与用户审批，本轮未做。

## 6. 交付

| 项 | 值 |
| --- | --- |
| 包 | `artifacts/handoff/PINGPONG_FINAL_DETECTOR_FOR_CAPTAIN.zip`，21,200,144 B，`4d63d890898f0738184bd45237d6dca01b1b36661d12c25b911a02f26321fbd4` |
| 主模型 | `pingpong_yolov8n_gray_3cls_v3_960.onnx`，12,161,114 B，`b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba` |
| 备用模型（不推荐） | `ball_v6_round2.onnx`，12,159,554 B，`d32b98d6a5a986b527654a7a34656a96d6d79a2702440bfffb36cf49dd685383` |
| 解压复验 | ✅ 12 个文件，包内 ONNX 哈希一致，包内脚本可独立跑通（10 帧，52.9 ms/帧） |

## 7. 未完成（如实）

- 无 OV9281 真实相机视频验证（仓库无此类素材）；
- 无 RKNN/NPU 转换与板端测试（工具链未安装）；
- 无 C++ 编译验证（无编译器）；
- 无 GPU 加速（ORT 无 CUDA provider）；
- val 是历史开发验证集（V2–V7 反复使用），**不是独立测试集**。
