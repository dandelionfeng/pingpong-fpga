# 统一三分类乒乓球检测模型 · 队长交付说明（实验候选 EXPERIMENTAL）

**状态：EXPERIMENTAL —— 可用于试用与集成联调，尚未通过正式验收，也没有任何 RK3576 板端证据。**

## 1. 这是什么

一个真正的**单次推理输出三类**的 YOLOv8n 模型（不是三个模型拼在一起）：

| class id | 名称 | 说明 |
| --- | --- | --- |
| 0 | `ball` | 乒乓球 |
| 1 | `hand` | 手 |
| 2 | `racket` | 球拍 |

- 权重：`pingpong_yolov8n_gray_3cls_v2_960.onnx`
- 输入：`images` `[1, 3, 960, 960]` float32，NCHW
- 输出：`output0` `[1, 7, 18900]`，即 `4 个框参数 + 3 个类别分数`，**图内不含 NMS**

## 2. 输入约定（与 C++ DetectorBackend 一致，务必按此实现）

1. 相机给的是 **GRAY8**（单通道 8bit）；
2. **灰度直接复制成 3 个通道**（R=G=B=gray），不要做彩色转换；
3. 等比缩放到 960×960，**letterbox**：比例 `s = min(960/w, 960/h)`，四周用 **114** 填充；
4. 归一化 `float32 = pixel / 255.0`，排布 `NCHW`；
5. 通道顺序：因为三通道相同，BGR/RGB 无差别。

```
scale = min(960 / W, 960 / H)
nw, nh = round(W*scale), round(H*scale)
canvas = full((960,960), 114)
pad_x, pad_y = (960-nw)//2, (960-nh)//2
canvas[pad_y:pad_y+nh, pad_x:pad_x+nw] = resize(gray, (nw,nh))
tensor = (canvas[None,None] -> 3ch -> float/255)
```

## 3. 输出解码

对每个 anchor：`score_class = sigmoid(out[4 + c])`，取最大者作为该框类别与置信度。

```
cx = out[0], cy = out[1], w = out[2], h = out[3]        # 输入尺度像素（960 空间）
x1 = (cx - w/2 - pad_x) / scale                          # 还原到原图像素
y1 = (cy - h/2 - pad_y) / scale
x2 = (cx + w/2 - pad_x) / scale
y2 = (cy + h/2 - pad_y) / scale
```

- **坐标定义**：左上角为原点、x 向右、y 向下，单位是**原图像素**（不是归一化）。
- **NMS**：按类分别做，IoU 0.50，`max_det` 建议 30–60。
- **推荐阈值**（在 val 上扫过，见 `EVALUATION_REPORT.md`）：**conf = 0.25** 作为统一默认；
  若分门限，可 `ball 0.20 / hand 0.25 / racket 0.25`。

## 4. 怎么跑

```powershell
# 1) 单张图
python infer_unified_3cls.py --source path\to\frame.jpg --out out

# 2) 整个文件夹
python infer_unified_3cls.py --source path\to\frames --out out --conf 0.25

# 3) 视频
python infer_unified_3cls.py --source path\to\clip.mp4 --out out --conf 0.25 --stride 1

# 4) 只要球和球拍
python infer_unified_3cls.py --source clip.mp4 --classes ball,racket
```

输出：
- `out\vis\*.jpg` 或 `out\vis\<clip>_3cls.mp4`：带框可视化（ball 黄、hand 绿、racket 红）
- `out\*.json` / `out\*.jsonl`：逐帧检测结果（`xyxy` 原图像素 + `xyxy_norm` 归一化 + `score` + `class_id`）

依赖：`numpy`、`opencv-python`、`onnxruntime`（CPU 即可）。
参考耗时：**约 49 ms/帧**（960 输入，4 线程，ONNX Runtime CPU，仅推理不含前后处理）。

## 5. 实测指标（val = 509 图，**不是独立测试集**）

| 类别 | GT 框 | P | R | F1 | AP50 | AP50-95 |
| --- | --- | --- | --- | --- | --- | --- |
| ball | 100 | 0.684 | 0.475 | — | 0.519 | 0.161 |
| hand | 1,172 | 0.666 | 0.557 | — | 0.613 | 0.290 |
| racket | 176 | 0.726 | 0.679 | — | 0.735 | 0.354 |
| 总体 | 1,448 | 0.692 | 0.571 | — | **0.623** | **0.268** |

（上表为 ultralytics val 的 AP 口径；固定阈值下的 TP/FP/FN 见 `EVALUATION_REPORT.md`。）

## 6. 已知限制（请务必看）

1. **ball 召回偏弱（0.475）**：这是目前最大短板，比单独的 ball 模型差。
2. **标签完整性不完美**：tabletennis 帧只标了 ball+racket、没标 hand；hand 帧只标了 hand。
   训练时这些"没标的类别"会被模型当作背景 → 统一模型的各类指标**不能**和单独模型直接比。
3. **验证集不是独立测试集**：val 与训练来自同一批数据源（按比赛/视频隔离，无帧级泄漏，
   但没有第三方独立集），所以这些数字是**域内验证**，不是泛化证明。
4. **没有真实 OV9281 数据验证**：仓库里没有这类视频，队长实测反馈是目前唯一的真实域信号。
5. **RKNN/NPU 未做**，板端未跑，**不要把它当成已在 RK3576 上跑通**。

## 7. 与三个独立模型的关系

| | 独立模型 | 统一模型 |
| --- | --- | --- |
| 推理次数 | 3 次（ball / hand / racket 各一个网络） | **1 次** |
| 参数量 | 3 × ~6 MB | **1 × ~6 MB** |
| 各类精度 | 各自在专项数据上更好 | 明显更低，尤其 ball |
| 适用 | 追求精度 | 追求延迟/内存、或需要三类同帧一致性 |

**建议**：先用统一模型做联调与延迟评估；正式判罚链路仍建议按类别选用专项模型，
直到统一模型在真实域把 ball 召回补上来。

## 8. 文件清单

| 文件 | 说明 |
| --- | --- |
| `pingpong_yolov8n_gray_3cls_v2_960.onnx` | 模型本体（sha256 见 `SHA256SUMS.txt`） |
| `infer_unified_3cls.py` | 参考推理脚本（图片/文件夹/视频） |
| `MODEL_CARD.md` | 模型卡：训练数据、训练配置、指标、限制 |
| `EVALUATION_REPORT.md` | 逐类评测明细（含两个阈值的 TP/FP/FN） |
| `INPUT_OUTPUT_PROTOCOL.md` | 给 C++ 集成用的输入输出协议 |
| `sample_hand.jpg` / `sample_racket.jpg` | 三类检测可视化示例 |
| `SHA256SUMS.txt` | 全部文件校验和 |
