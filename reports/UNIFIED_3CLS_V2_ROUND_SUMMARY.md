# 统一三分类 YOLO · 今晚交付记录

日期：2026-10-24　分支：`codex/c-pc-detector`
交付包：`artifacts/handoff/UNIFIED_3CLS_V2_FOR_CAPTAIN.zip`

## 一、是否真的训练出了三分类模型

**是。** 一个 YOLOv8n，**单次推理**输出 `ball/hand/racket` 三类，不是三个 ONNX 拼的，
也不是只改了类别名。

- 权重：`artifacts/runs/unified_3cls_v2/weights/best.pt`
- ONNX：`artifacts/files/models/unified_3cls_v2/pingpong_yolov8n_gray_3cls_v2_960_960.onnx`
  → 交付时重命名为 `pingpong_yolov8n_gray_3cls_v2_960.onnx`
- 输入 `[1,3,960,960]` → 输出 `[1,7,18900]`（4 框 + 3 类）
- 类别固定 `0=ball, 1=hand, 2=racket`

## 二、per-class 指标（val 509 图，**非独立测试集**）

| 类别 | GT | P | R | AP50 | AP50-95 |
| --- | --- | --- | --- | --- | --- |
| ball | 100 | 0.684 | **0.475** | 0.519 | 0.161 |
| hand | 1,172 | 0.666 | 0.557 | 0.613 | 0.290 |
| racket | 176 | 0.726 | 0.679 | 0.735 | 0.354 |
| **overall** | 1,448 | 0.692 | 0.571 | **0.623** | **0.268** |

固定阈值 TP/FP/FN（本仓库统一匹配 IoU≥0.5）：

| conf | 类别 | TP | FP | FN | P | R | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.25 | ball | 46 | 18 | 54 | 0.719 | 0.460 | 0.561 |
| 0.25 | hand | 660 | 278 | 512 | 0.704 | 0.563 | 0.626 |
| 0.25 | racket | 121 | 42 | 55 | 0.742 | 0.688 | 0.714 |

## 三、训练成本

| 项 | 值 |
| --- | --- |
| 实际轮数 | **15 / 15**（跑满，patience 6 未触发） |
| 最佳 epoch | **14**（mAP50 0.6263 / mAP50-95 0.2676） |
| 耗时 | **0.471 h ≈ 28 分钟** |
| GPU | RTX 4060 Laptop 8.6 GB，CUDA 12.1，AMP |
| 配置 | imgsz 960，batch 12，AdamW lr0 3e-4，cos_lr，mosaic 0.3（close 5），seed 42 |
| 初始化 | `artifacts/runs/pingpong_3cls_v1/weights/best.pt`（同为 3 类，兼容） |
| 数据 | `pingpong_unified_3cls_v3`：train 3,910 / val 509 |

## 四、模型文件与哈希

| 文件 | 大小 | SHA256 |
| --- | --- | --- |
| `artifacts/runs/unified_3cls_v2/weights/best.pt` | 6,271,011 B | `73f460a8276afbc4a61e56dac21debd50bb6409da643fe3f83079b8c2c3d3347` |
| `artifacts/files/models/unified_3cls_v2/…_960_960.onnx` | 12,161,114 B | `ed4653652c1735cfc1dec32354b3591a5f6ebbdc8b1d5c5eadd7dd276e36645f` |
| `artifacts/handoff/UNIFIED_3CLS_V2_FOR_CAPTAIN.zip` | 10,827,927 B | `d843164a543f2c48dfd687afb8b3a552ff3cce1cf08a77d40da6c09de4287be8` |

## 五、ONNX 验证

- 加载 ✅；输入/输出维度 ✅；类别顺序 ✅
- **PT/ONNX 一致**：原始 logits 差 1.40e-03（float32 噪声），**sigmoid 后 4.17e-07**，top-1 6/6 一致
- 实际推理 ✅：10 张样例图 → ball 5 / hand 14 / racket 8
- 坐标还原 ✅ 到原图像素；可视化正常
- 耗时 **49.2 ms/帧**（CPU，4 线程，仅推理）
- **ZIP 解压后**再次运行推理成功（10 帧同结果）

## 六、三类是否都真的检出

**是。** 交付脚本在样例上同时输出三类框（例如 racket 图：ball 2 + racket 1；
hand 图：3 个 hand 框 0.84/0.41/0.28）。没有出现某类完全失效。

## 七、与三个独立模型相比

**不能直接比**（各自评测集不同），定性结论：

- 统一模型**没有任何一类超过专项模型**；
- ball 最弱（R 0.475），这是标签不完整 + 三任务共享容量的直接后果；
- 优势是：**1 次推理替代 3 次**，参数量 1×6 MB 替代 3×6 MB。

## 八、已完成 / 未完成

| 项 | 状态 |
| --- | --- |
| 真正的三分类训练 | ✅ 15 轮，28 分钟 |
| per-class 评测（P/R/AP50/AP50-95/TP/FP/FN） | ✅ |
| ONNX 导出 + PT/ONNX parity | ✅ |
| 队长交付包（ONNX+README+MODEL_CARD+协议+评测+示例+脚本+校验和） | ✅ |
| ZIP + 解压复验 | ✅ |
| **独立测试集评测** | ❌ **NOT DONE**（无独立集，只有 val） |
| **OV9281 真实域验证** | ❌ **NOT DONE**（仓库无此类视频） |
| **RKNN/NPU 转换与板端** | ❌ **NOT RUN** |
| **C++ 引擎实测** | ❌ **NOT RUN**（未改任何 C++ 文件） |
| **正式验收** | ❌ 未通过，模型状态为 **EXPERIMENTAL** |

## 九、Git

本地提交（未推送）：见 `git log`。未改 main、未 force push、未合并 PR、
未覆盖旧统一 ONNX（`10a83aa2…`）与 V2.4 交付包（`7edf80ed…`）、未改 Ball/Hand 模型。
