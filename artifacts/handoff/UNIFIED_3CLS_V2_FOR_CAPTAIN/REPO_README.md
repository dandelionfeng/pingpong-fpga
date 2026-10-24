# 统一三分类乒乓球检测模型（仓库说明）

**状态：`EXPERIMENTAL` —— 实验候选，未通过正式验收。**

一个 YOLOv8n，**单次前向同时输出 ball / hand / racket**。不是三个 ONNX 拼接，也不是改类别名。

| 项 | 值 |
| --- | --- |
| 类别映射（固定） | `0 = ball`，`1 = hand`，`2 = racket` |
| ONNX 输入 | `images [1, 3, 960, 960]` float32（Gray8 → Gray3 → letterbox → /255） |
| ONNX 输出 | `output0 [1, 7, 18900]` = 4 个框参数 + 3 个类别分数，**图内无 NMS** |
| ONNX 文件 | `pingpong_yolov8n_gray_3cls_v2_960.onnx`，12,161,114 B |
| ONNX SHA256 | `ed4653652c1735cfc1dec32354b3591a5f6ebbdc8b1d5c5eadd7dd276e36645f` |
| 训练权重 | `artifacts/runs/unified_3cls_v2/weights/best.pt`，6,271,011 B |
| 权重 SHA256 | `73f460a8276afbc4a61e56dac21debd50bb6409da643fe3f83079b8c2c3d3347` |
| 队长交付 ZIP | `artifacts/handoff/UNIFIED_3CLS_V2_FOR_CAPTAIN.zip`，10,827,927 B |
| ZIP SHA256 | `d843164a543f2c48dfd687afb8b3a552ff3cce1cf08a77d40da6c09de4287be8` |

## 训练

| 项 | 值 |
| --- | --- |
| 架构 / 输入 | YOLOv8n / 960 |
| 初始化 | `artifacts/runs/pingpong_3cls_v1/weights/best.pt`（同为 3 类，兼容） |
| 数据 | `artifacts/files/datasets/pingpong_unified_3cls_v3`（由 `pingpong_3cls_v2` 抽平衡子集） |
| train / val | 3,910 图 / 509 图 |
| GT 框（train） | ball 1,978 / hand 3,123 / racket 4,790 |
| GT 框（val） | ball 100 / hand 1,172 / racket 176 |
| 轮数 / 最佳 epoch | 15 / 15（跑满）/ **14** |
| 耗时 / GPU | **28 分钟** / RTX 4060 Laptop 8.6 GB |
| 超参 | AdamW lr0 3e-4，cos_lr，batch 12，mosaic 0.3（close 5），scale 0.4，degrees 5，seed 42 |

## 验证集指标（509 图，**不是独立测试集**）

| 类别 | Precision | Recall | AP50 | AP50-95 |
| --- | ---: | ---: | ---: | ---: |
| Ball | 0.684 | 0.475 | 0.519 | 0.161 |
| Hand | 0.666 | 0.557 | 0.613 | 0.290 |
| Racket | 0.726 | 0.679 | 0.735 | 0.354 |
| **Overall** | **0.692** | **0.571** | **0.623** | **0.268** |

固定 `conf=0.25` 时的 TP/FP/FN：ball 46/18/54（P 0.719 R 0.460）、hand 660/278/512（P 0.704 R 0.563）、racket 121/42/55（P 0.742 R 0.688）。

## 怎么用

```powershell
cd artifacts\handoff\UNIFIED_3CLS_V2_FOR_CAPTAIN

python infer_unified_3cls.py --source path\to\frame.jpg --out out
python infer_unified_3cls.py --source path\to\frames --out out --conf 0.25
python infer_unified_3cls.py --source clip.mp4 --out out --conf 0.25
python infer_unified_3cls.py --source clip.mp4 --classes ball,racket
```

输出 `out/vis/*.jpg`（ball 黄 / hand 绿 / racket 红）与 `out/*.jsonl`（`xyxy` 原图像素 + 归一化 + score + class_id）。
参考耗时 **49 ms/帧**（ONNX Runtime CPU，4 线程，仅模型推理）。

依赖：`numpy`、`opencv-python`、`onnxruntime`。

## 已知限制（务必阅读）

1. **没有独立测试集** —— 上表是域内验证（按比赛/视频隔离，无帧级泄漏），不能当作泛化性能。
2. **没有真实 OV9281 场景验证** —— 仓库内无此类视频。
3. **尚未完成 RKNN/NPU 真机部署**，板端未跑。
4. **尚未完成 C++ 引擎实测**（本轮未改任何 C++ 文件）。
5. **Ball 召回 0.475 是最大短板**，明显弱于专项 ball 模型。
6. **源数据标签按数据集不完整**（tabletennis 帧无 hand 标注、hand 数据集无 ball/racket 标注），
   训练时未标注类别会被当作背景 —— 这是统一模型各类指标低于专项模型的根本原因。

**因此：本模型不能直接替换正式判罚链路，只作为实验候选供联调与延迟评估。**

## 相关文档

- `README_CAPTAIN.md` —— 队长使用说明（输入约定、解码、命令）
- `MODEL_CARD.md` —— 模型卡（数据、配置、指标、限制）
- `INPUT_OUTPUT_PROTOCOL.md` —— 给 C++ 集成的输入输出协议
- `EVALUATION_REPORT.md` —— 逐类评测明细（含两个阈值的 TP/FP/FN）
- `SHA256SUMS.txt` —— 交付目录内所有文件的校验和
- 仓库报告：`reports/UNIFIED_3CLS_V2_ROUND_SUMMARY.md`、`reports/UNIFIED_3CLS_DATA_AUDIT.md`
