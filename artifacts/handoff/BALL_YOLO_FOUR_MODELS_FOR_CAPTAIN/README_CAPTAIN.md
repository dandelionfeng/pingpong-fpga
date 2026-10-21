# 交付说明：四个乒乓球 YOLO 模型（给队长）

本包只做**模型资产整理、完整性验证、统一推理入口**。**不包含准确率对比，也不推荐模型**
——四个模型哪个更好，由队长用下面的工具自己测。

## 1. 包里有什么

```text
BALL_YOLO_FOUR_MODELS/
├── models/                     4 个 ONNX（与仓库原始文件逐字节一致）
│   ├── ball_yolo_v1_1280.onnx
│   ├── ball_roboflow_960.onnx
│   ├── ball_roboflow_1280.onnx
│   └── ball_v6_round2.onnx
├── config/model_manifest.json  每个模型的形状、类别、来源、哈希、已知限制
├── tools/
│   ├── eval_ball_models.py     统一推理入口（图片 / 文件夹 / 视频）
│   └── score_ball_models.py    用自带 GT 打分（命中数、P/R/F1、AP50、球心误差、空帧误检）
├── gt/images/                  42 张冻结测试图（1920×1080，彩色原图）
├── gt/annotations_json/        对应 GT（球 class_id=0，手 class_id=1，xyxy 像素坐标）
├── MODEL_SHA256.txt
└── THIRD_PARTY_NOTICES.md
```

## 2. 四个模型速览

| 模型编号 | 输入 | 大小 | 说明 |
| --- | --- | --- | --- |
| `ball_yolo_v1_1280` | 1280×1280 | 12,218,920 B | 项目 V1 基线（tabletennis + 521 张 BNDSTT 伪标签训练） |
| `ball_roboflow_960` | 960×960 | 12,159,554 B | Roboflow v3 混合训练，960 导出 |
| `ball_roboflow_1280` | 1280×1280 | 12,189,920 B | **同一份权重**，1280 导出 |
| `ball_v6_round2` | 960×960 | 12,159,554 B | 第 6 轮第二次尝试（COCO 初始化 + 降采样辅助数据） |

全部为 **单类 `ball`**、输出 YOLOv8 原始检测头。

> 重要：`ball_roboflow_960` 与 `ball_roboflow_1280` 是**同一组权重的两种导出尺寸**，
> 不是两个不同的模型。分别测它们可以看出"输入分辨率"的影响。

**输入约定（四个模型相同）**：BGR 帧 → 转灰度 → 复制成 3 通道 → letterbox 到方形 →
`/255` → NCHW float32。**用彩色 RGB 直接喂会改变分数**，工具里已经按 gray3 处理。

## 3. 环境

```powershell
# 在项目根目录，使用现有虚拟环境
.\.venv\c-detector\Scripts\python.exe -c "import cv2, numpy, onnxruntime; print('ok')"
```

依赖：`numpy`、`opencv-python`、`onnxruntime`（CPU 即可）。

## 4. 跑单张图 / 一个文件夹

```powershell
cd artifacts\handoff\BALL_YOLO_FOUR_MODELS
..\..\..\.venv\c-detector\Scripts\python.exe tools\eval_ball_models.py `
  --model ball_yolo_v1_1280 --source gt\images --out out\v1
```

输出：

- `out\v1\predictions.jsonl`：每张图一行，含 `image / width / height / inference_ms /
  detections[{xyxy, score, class_id, xyxy_norm}]`，**坐标为原图像素**；
- `out\v1\vis\*.jpg`：画了框的可视化图。

## 5. 跑视频

```powershell
..\..\..\.venv\c-detector\Scripts\python.exe tools\eval_ball_models.py `
  --model ball_roboflow_960 --source path\to\clip.mp4 --out out\video --stride 1
```

输出 `out\video\<clip>.jsonl`（逐帧，含 `frame_index`）与 `out\video\vis\<clip>_annotated.mp4`。

常用参数：`--conf`（默认 0.10）、`--iou`（默认 0.50）、`--max-det`（默认 30）、`--stride`。

## 6. 自己算准确率

```powershell
# 1) 先跑推理，写出 predictions.jsonl
..\..\..\.venv\c-detector\Scripts\python.exe tools\eval_ball_models.py `
  --model ball_yolo_v1_1280 --source gt\images --out out\v1

# 2) 再用同一套匹配规则打分
..\..\..\.venv\c-detector\Scripts\python.exe tools\score_ball_models.py `
  --predictions out\v1\predictions.jsonl --conf 0.10
```

评分规则（与项目内部一致）：

- 一对一贪心匹配，**IoU ≥ 0.5**；
- 匹配成功后球心距离 **≤ 50 px** 记为"命中"；
- 球心误差**只统计匹配成功的检测**；
- AP50 用 101 点插值；
- 空帧上任何检测框都算误检。

评测集统计：**42 张图 / 36 个有球帧 / 36 个球框 / 6 个空帧**，图像均为 **1920×1080**。

> ⚠️ 该 BNDSTT 冻结集在项目内部已多轮使用过（训练外的诊断集），
> **不能把它上的结果包装成"全新独立测试"**。若要更独立的结论，需要另取未参与过项目实验的片段。

## 7. 出错时

工具对以下情况会**明确报错并返回非 0 退出码**，不会静默返回空结果：

| 情况 | 行为 |
| --- | --- |
| `--model` 不在四个编号里 | 列出可用编号，退出码 2 |
| 模型文件缺失 | 打印绝对路径，退出码 2 |
| `--source` 不存在 | 退出码 2 |
| 图片无法解码 | 打印文件名，退出码 3 |
| 视频打不开 / 无法写输出 | 退出码 3 |
| ONNX 输入形状不是 `[1,3,S,S]` | 退出码 3 |

## 8. 已知限制

1. 四个模型都只输出 `ball` 一个类，没有手/拍/台面。
2. 球馆远景下分数普遍偏低（常见 < 0.3），这是本项目最终仍用 BallTrack 作为正式球检测后端的原因。
3. `ball_yolo_v1_1280` 的 `.pt` 与 `.onnx` 两条推理路径在项目里曾被观察到结果不一致
   （同权重 7/36 vs 15/36，见 `reports/BALL_YOLO_V5_ROBOFLOW_REPORT.md` §4.2）。
   本项目对外引用的 15/36 是 **ONNX 路径**的数字，也就是本包里的这个文件。
4. 三个后训练模型（两条 Roboflow + 第 6 轮）的训练数据里含 Roboflow `ping pong detection v3`
   （**CC BY 4.0**），如对外发布需保留署名，见 `THIRD_PARTY_NOTICES.md`。

## 9. 怎么核对文件没坏

```powershell
Get-FileHash models\*.onnx -Algorithm SHA256
# 与 MODEL_SHA256.txt 逐行比对，四个都应一致
```
