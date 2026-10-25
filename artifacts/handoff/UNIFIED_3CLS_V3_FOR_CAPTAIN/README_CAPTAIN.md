# 统一三分类 V3 · 队长交付说明（EXPERIMENTAL）

**状态：`EXPERIMENTAL` —— 相比 V2 在 Ball 与 Racket 上有实测提升，但仍在同一验证集上评测，
没有独立测试集、没有 OV9281 真实域验证、没有 RKNN/板端与 C++ 实测。**

## 1. 与 V2 的关系

| | V2 | **V3（本包）** |
| --- | --- | --- |
| ONNX | `pingpong_yolov8n_gray_3cls_v2_960.onnx` | `pingpong_yolov8n_gray_3cls_v3_960.onnx` |
| SHA256 | `ed465365…6e36645f` | `b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba` |
| 训练数据 | train 3,910 图 | **train 4,431 图**（+521 张 BNDSTT 真实域球帧） |
| ball GT | 1,978 框 | **2,499 框（+26.3%）** |
| hand GT | 3,123 框 | 3,698 框（+575 自动候选，**待人工复核**） |
| racket GT | 4,790 框 | 4,790 框（未变） |
| val | 509 图 | **同一 509 图**（对比公平） |

输入 `[1,3,960,960]` float32，输出 `[1,7,18900]`，类别固定 `0=ball, 1=hand, 2=racket`，
Gray8 → Gray3 → letterbox → /255，与 V2 **完全同一协议**。

## 2. 实测指标（val 509 图，**非独立测试集**）

### ultralytics AP 口径

| 类别 | V2 P | **V3 P** | V2 R | **V3 R** | V2 AP50 | **V3 AP50** | V2 AP50-95 | **V3 AP50-95** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Ball | 0.684 | **0.827** | 0.475 | 0.460 | 0.519 | **0.538** | 0.161 | 0.154 |
| Hand | 0.666 | 0.679 | 0.557 | 0.538 | 0.613 | 0.607 | 0.290 | 0.285 |
| Racket | 0.726 | 0.734 | 0.679 | **0.727** | 0.735 | **0.738** | 0.354 | 0.347 |
| **Overall** | 0.692 | **0.746** | 0.571 | 0.575 | 0.623 | **0.627** | **0.268** | 0.262 |

### 固定 conf = 0.25（部署口径，IoU 0.5 一对一匹配）

| 类别 | V2 TP/FP/FN | V2 P / R / F1 | **V3 TP/FP/FN** | **V3 P / R / F1** |
| --- | --- | --- | --- | --- |
| Ball | 46/18/54 | 0.719 / 0.460 / 0.561 | 47/5/53 | **0.904 / 0.470 / 0.618** |
| Hand | 660/278/512 | 0.704 / 0.563 / 0.626 | 654/292/518 | 0.691 / 0.558 / 0.618 |
| Racket | 121/42/55 | 0.742 / 0.688 / 0.714 | 133/42/43 | **0.760 / 0.756 / 0.758** |

## 3. 结论（该说的都写上）

**有提升的**：
- Ball：F1@0.25 **+5.7 点**（0.561→0.618），精度 **+18.5 点**（0.719→0.904），AP50 **+0.019**；
- Racket：召回 **+4.8 点**（0.688→0.756），F1@0.25 **+4.4 点**（0.714→0.758），AP50 +0.003；
- Overall mAP50 **+0.005**（0.623→0.627）。

**没提升 / 略降的**：
- Ball Recall 仍然低（0.460，V2 是 0.475，−0.015）——**没有解决**；
- Hand 几乎持平但略降（AP50 0.613→0.607，F1 0.626→0.618）；
- AP50-95 总体略降（0.268→0.262）。

**判定**：改动带来的收益是**真实但有限**的，主要集中在"少误检 + 球拍召回"。
它不足以宣称"Ball 检测已经够好"，Ball Recall 0.46 仍是最大短板。

## 4. 怎么跑

```powershell
cd artifacts\handoff\UNIFIED_3CLS_V3_FOR_CAPTAIN

python infer_unified_3cls.py --source path\to\frame.jpg --out out --conf 0.25
python infer_unified_3cls.py --source path\to\frames --out out --conf 0.25
python infer_unified_3cls.py --source clip.mp4 --out out --conf 0.25
python infer_unified_3cls.py --source clip.mp4 --classes ball,racket
```

依赖 `numpy` + `opencv-python` + `onnxruntime`。参考延迟 **74 ms/帧**（CPU，4 线程，仅推理；
V2 为 70.4 ms）。

## 5. 已知限制（重要）

1. **无独立测试集**：所有数字来自与训练同源的 val（按比赛/视频隔离，无帧级泄漏）。
2. **无真实 OV9281 验证**：仓库里没有这类视频。
3. **RKNN/NPU 未做、板端未跑、C++ 引擎未实测**。
4. **标签完整性仍不完美**（详见 `reports/UNIFIED_V3_LABEL_AUDIT.md`）：
   - 新增的 521 张 BNDSTT 球帧**没有 racket 标注**；
   - 其中 575 个 hand 框是**专项模型自动生成的候选**，未经人工逐框确认；
   - tabletennis 帧仍无 hand 标注，hand 数据集仍无 ball/racket 标注。
5. Ball Recall 0.46 偏低，仍不建议单独依赖本模型做发球判罚的球检测。

## 6. 文件清单

| 文件 | 说明 |
| --- | --- |
| `pingpong_yolov8n_gray_3cls_v3_960.onnx` | 模型（12,161,114 B） |
| `infer_unified_3cls.py` | 参考推理脚本（默认已指向 v3 模型） |
| `MODEL_CARD.md` | 模型卡：数据、训练、指标、限制 |
| `EVALUATION_REPORT.md` | 逐类评测 + V2/V3 对比明细 |
| `sample_training_frames.jpg` | 新增训练帧示例（黄=ball GT，绿=自动 hand 候选） |
| `sample_detection.jpg` | 实际检测示例 |
| `SHA256SUMS.txt` | 校验和 |

回滚：直接继续使用 V2（`artifacts/handoff/UNIFIED_3CLS_V2_FOR_CAPTAIN/`），两者协议完全一致。
