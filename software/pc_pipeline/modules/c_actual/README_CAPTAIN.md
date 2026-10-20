# C 端感知 —— 队长联调包（C_ACTUAL_INTERFACE_V2_4）

**V2.4 的默认跑法是一个模型**：`pingpong_yolov8n_gray_3cls_960.onnx` 同时给 hand 和
racket，每帧只跑一次 YOLO。老的 hand+racket 两个模型仍在包里，`--unified-model` 不写就
退回到 V2.3 的行为。

## 1. 先跑起来（30 秒）

1. 把 ZIP 解压到一个**纯英文路径**目录（例如 `D:\c_iface`）
2. 打开 PowerShell，`cd` 到解压出来的目录
3. 执行：

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1
```

`run_demo.ps1` 会自动判断用统一模型还是分离模型（统一模型在就用统一模型）。

4. 看结果：

- `out\result_image.jsonl`、`out\result_video.jsonl` —— 每帧一行 JSON
- `out\overlay_image.png`、`out\overlay_video.mp4` —— 画了 ball 中心 / hand 框 / racket 框

`run_demo.ps1` 会先用 `examples\` 里的样例图跑一次，再用样例视频跑一次。
模型文件缺失时会明确打印 `MISSING_MODEL` 并以退出码 2 结束，不会抛异常。

> **为什么必须用英文路径**：Windows PowerShell 5.1 在向原生 .exe 传参时会把非 ASCII
> 字符弄坏（引擎本身支持 UTF-8 中文路径，但 5.1 的传参层不行）。用 PowerShell 7+ 可避免。

## 2. 跑你自己的视频

推荐（统一三类模型，一次推理出 hand + racket）：

```powershell
.\bin\c_perception_cli.exe `
  --video 你的视频.mp4 `
  --ball-model    models\balltrack_tracknetv3.onnx `
  --unified-model models\pingpong_yolov8n_gray_3cls_960.onnx `
  --config config\inference.yaml `
  --output out\result.jsonl `
  --overlay out\overlay.mp4
```

老的分离模型（V2.3 行为，仍然支持）：

```powershell
.\bin\c_perception_cli.exe `
  --video 你的视频.mp4 `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray_final_v3_960.onnx `
  --racket-model models\racket_yolov8n_gray.onnx `
  --output out\result.jsonl
```

单张图：把 `--video` 换成 `--image` 即可。

只检查模型能否加载：

```powershell
.\bin\c_perception_cli.exe --self-test --image examples\sample_frame.png `
  --ball-model    models\balltrack_tracknetv3.onnx `
  --unified-model models\pingpong_yolov8n_gray_3cls_960.onnx
```

## 3. 输入是什么

**你只需要给单通道 8 位灰度图 `GRAY8`（OpenCV `CV_8UC1`），原图尺寸。**

引擎内部自己完成 gray3、letterbox、归一化、NMS、坐标还原。
**你不需要**自己做这些，也**不需要**指定任何模型输入分辨率。

> 如果你的输入是彩色视频/图片，CLI 会**先转成 GRAY8** 再喂给模型 ——
> demo 不会偷偷用彩色。这和 OV9281 真实链路一致。

## 4. 输出是什么

JSONL，每行一帧：

```json
{
  "frame_id": 12,
  "timestamp": 0.4,
  "width": 1280, "height": 720,
  "ball":  { "state": "DETECTED", "detected": true, "confidence": 0.78,
             "center": [829.0, 320.5], "region": [820.0, 312.0, 18.0, 17.0],
             "bbox_semantics": "heatmap_component" },
  "hands":   [ { "class": "hand",   "confidence": 0.42, "bbox": [1181.0, 495.0, 36.0, 28.0] } ],
  "rackets": [ { "class": "racket", "confidence": 0.77, "bbox": [838.0, 263.0, 33.0, 40.0] } ],
  "infer_ms": 1800.0
}
```

坐标全部是**原图坐标**。

- `ball.state`：`DETECTED` / `WARMUP` / `DROPOUT` / `INVALID`
  - `WARMUP`：BallTrack 是时序模型，前 4 帧没有历史，**没有做预测**，这是正常的
  - 只有 `DETECTED` 才算这一帧看到了球
- `ball.center` 是球心（推荐用这个）；`region` 是热图连通域，**不是球直径**
- `hands` 是**真实 YOLO hand bbox**

**hand 角色（持拍手 / 抛球手）由 B 判断，C 不判断。**
**trajectory / Kalman / 合法性也由 B 负责。**

### 出错时不会静默

如果某个 ONNX 的输入形状与引擎构造的张量不一致，结果里会出现明确错误码：

`YOLO_INPUT_CONTRACT_MISMATCH` / `YOLO_TENSOR_SIZE_MISMATCH` /
`YOLO_INFERENCE_FAILED` / `YOLO_OUTPUT_CONTRACT_MISMATCH`

并同时打到 stderr，**不会在没有检测时假装"本帧没有手"**。

## 5. 各模型的输入分辨率由模型自己决定

| 模式 | 检测器 | 输入尺寸 | 来源 |
| --- | --- | --- | --- |
| 统一（默认） | unified | **960 × 960** | 从该 ONNX 的 input shape 自动读取 |
| 分离（legacy） | hand | 960 × 960 | 从 hand ONNX 的 input shape 自动读取 |
| 分离（legacy） | racket | 640 × 640 | 从 racket ONNX 的 input shape 自动读取 |
| 两种模式 | ball (BallTrack) | 512 × 288 | 官方契约，15 通道 gray3 |

配置里**没有** `imgsz` 键，不需要你填。

### 统一模型的类别顺序是契约

`0 = ball`、`1 = hand`、`2 = racket`。加载时会用输出通道数（`4 + 类别数`）校验；不是 3 类
会直接报 `UNIFIED_MODEL_CLASS_MISMATCH` 并拒绝加载，**不会把 racket 当 hand 输出**。

**统一模型里的 ball 类不会被输出**：冻结接口里 ball 只有一个来源（BallTrack）。同时给两个
定义不同的球位置会让 B 无法判断该信谁。

## 6. 接进项目（SDK）

`bin/` 里是可执行 demo；`sdk/` 里是给 C++ 集成的接口：

```
sdk/include/c_perception_engine.hpp   # CPerceptionEngine 头文件
sdk/lib/c_actual.lib                  # 静态库
sdk/lib/c_actual_pipeline_bridge.lib  # DetectorBackend 桥接静态库
sdk/detector_backend_c_actual.cpp     # 桥接源码
```

也可以直接用仓库里的 `DetectorBackend`：

```cpp
DetectorContext ctx;      // ctx.gray 是 CV_8UC1 GRAY8
ctx.meta = ...; ctx.eye = Eye::Left;
DetectionResult r = detector->infer(ctx, stop, timeoutMs);
// r.boxes 就是上面第 4 节的 schema
```

V2.4 在 `ModelPaths` 里新增了一个**可选**字段：

```cpp
c_actual::ModelPaths paths;
paths.ball_track = "...";                      // 必需
paths.unified    = "...3cls_960.onnx";         // 可选：设置后一次推理出 hand+racket
// paths.hand / paths.racket 在设置 unified 后被忽略
```

`PerceptionResult` 同时多了一个 `unified_model` 字段（未用统一模型时为空）。
统一模式下 `DetectorBackend::mode()` 返回 `actual-model-c-actual-v2.4-unified`；
分离模式仍是 `actual-model-c-actual-v2`。**如果你的代码按 `mode()` 字符串精确比较，请改成
前缀匹配或同时接受这两个值。** 详见 `INTERFACE_CONTRACT.md` 第 9 节。

## 7. 可选：时序确认（B 侧工具，不改变 C 输出）

`python/temporal_hand_filter.py` 读取 C 的 JSONL，输出经过时序确认的 hand：

```powershell
python python\temporal_hand_filter.py --input out\result_video.jsonl --output out\confirmed.jsonl
```

- **不改变 C 的原始 `DetectionResult`**
- 在**真正连续**的 40 帧样例上只抑制约 **3%** 的框（66→64）
- **在项目评测集上无法测量**：该集合 36 个相邻标注帧对里只有 4 对是连续帧，
  其余间隔 4–6 帧，任何时序指标都属 `TEMPORAL_METRIC_LIMITED`
- 因此：**它不是降误检手段**，不要指望靠它压 FP

## 8. 三类成绩（如实，V2.4 实测）

三个评测集职责不同，**不能互相代替**：

| 评测集 | 内容 | 能回答什么 |
| --- | --- | --- |
| `val_3cls` | 训练侧 val，250 图：ball 233 / racket 550 | 同域 ball / racket |
| `bodyhands_val` | BodyHands 留出 1258 图 / 3332 hand 框 | 公开域 hand |
| `bndstt_manual` | 真实目标域人工标注 41 图 / 54 hand 框 / 5 session | 真实域 hand |

`val_3cls` **一个 hand 框都没有**，所以训练日志里的 mAP50 **是 ball+racket 两类的数**，
不能当三类成绩引用。

| 模型 @ 集 | 类别 | P | R | F1 | AP50(11pt) | AP50(101pt) | TP/FP/FN |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unified @ val_3cls | ball | 0.8011 | 0.6223 | 0.7005 | 0.6659 | 0.6764 | 145/36/88 |
| unified @ val_3cls | racket | 0.8333 | 0.7818 | 0.8068 | 0.7955 | **0.8192** | 430/86/120 |
| racket_v1 @ val_3cls | racket | 0.8028 | 0.7400 | 0.7701 | 0.7428 | 0.7580 | 407/100/143 |
| unified @ bodyhands_val | hand | 0.6286 | 0.4988 | 0.5562 | 0.5072 | 0.5140 | 1662/982/1670 |
| hand_v3 @ bodyhands_val | hand | 0.8077 | 0.7260 | 0.7647 | 0.7726 | 0.7921 | 2419/576/913 |
| unified @ bndstt_manual | hand | **0.6667** | 0.4444 | **0.5333** | **0.4766** | **0.4606** | 24/12/30 |
| hand_v3 @ bndstt_manual | hand | 0.4023 | **0.6481** | 0.4965 | 0.4670 | 0.4544 | 35/52/19 |

阈值：hand 0.25、racket 0.30（**没有用任何评测集调过**）。

怎么读这张表：

- **racket**：统一模型在唯一有 racket 真值的集合上**更好**（AP50 0.8192 vs 0.7580）。
- **hand**：统一模型在真实域 AP50 略高（0.4766 vs 0.4670），但**更保守**——同样 0.25 阈值下
  recall 掉到 0.4444（漏 30/54），precision 升到 0.6667。公开发球域（BodyHands）明显更差。
- **结论**：统一模型目前**不能无脑替换**分离模型。`run_demo.ps1` 默认仍走分离模型，
  统一模型用 `-Unified` 显式打开。
- **ball**：统一模型的 ball 头**不输出**，也不用来评分；ball 一直是 BallTrack。
  （在 BNDSTT 域样例片段上这个 ball 头的最高分只有 0.010，说明它没有跨域能力——
  这也印证了不该拿它当 ball 来源。）

### 已知的未解决点（必须如实保留）

在同一段 BNDSTT 域 40 帧样例上，统一模型的 racket 分数最高只有 **0.003**，而专用
640 racket 模型最高 **0.806**。BNDSTT 没有 racket 真值，**无法判断谁的框是真的**：

- 可能是统一模型在真实域看不到拍；
- 也可能是 640 模型在该域把"手/拍重叠区"误当拍（样例里 hand 框与 racket 框几乎重合）。

在拿到带 racket 标注的真实域数据之前，**不要把 racket 切到统一模型**。

## 8.1 V2.3 的手部历史（保留原始数字）

评测集：`BNDSTT_MANUAL_GT_V1`，**41 图 / 54 个 hand box**，5 个 session，conf = 0.25。

| 指标 | V2.2（旧 hand） | **V2.3** |
| --- | --- | --- |
| Precision | 0.3626 | **0.4023** |
| Recall | 0.6111 | **0.6481** |
| F1 | 0.4552 | **0.4965** |
| AP50 | 0.3789 | **0.4670** |
| TP/FP/FN | 33/58/21 | **35/52/19** |

V2.4 用独立评分器重跑了 V2.3 模型，**逐位复现**了上面这一行（P 0.4023 / R 0.6481 /
F1 0.4965 / AP50 0.4670 / 35-52-19），说明评分口径一致，可以横向比较。

**请勿外推。** 只有 41 张图、54 个框、单次测量。可信的是**方向**，不是这些数字对其他
球场、光照、机位或球员服装的泛化能力。

## 9. 当前速度说明

同一段 40 帧 1920×1080 样例（CPU，ONNX Runtime 1.20.1，本机，两次测量）：

| 模式 | 平均耗时 | hand 框 | racket 框 |
| --- | --- | --- | --- |
| 分离（hand 960 + racket 640） | **1.53–1.95 s/帧** | 66 | 28 |
| 统一（1 × 960） | **1.21–1.39 s/帧** | 11 | 0 |

统一模型每帧只跑一次 YOLO，**快 20–30%**；但 BallTrack 仍是主要成本，所以整体**仍然远非实时**。

> 这次样例上的框数差异（66→11、28→0）是**真实存在的差异**，见第 8 节"已知的未解决点"。
> 不要只看"更快"就切过去。

## 10. 依赖

- Microsoft Visual C++ 2015-2022 运行库（x64）
- `bin/` 里已带 `onnxruntime.dll`、`opencv_world4100.dll`、
  `opencv_videoio_ffmpeg4100_64.dll`
- **不需要** CUDA、**不需要** Python、**不需要**自己编译
- 仅当使用第 7 节的可选时序工具时才需要 Python

## 11. 已知限制（如实）

1. hand 成绩是小样本单次测量（41 图 / 54 框 / 5 session），**不代表泛化**。
2. **CPU 非实时**：分离 1.53 s/帧、统一 1.21 s/帧（1920×1080，本机）。
3. **未做 RKNN 转换、未上板、无 NPU 实测**；`BOARD VERIFIED = NO`。
4. **未接真实 OV9281 相机**：灰度链路在公开数据与解码视频帧上验证。
5. BallTrack 背景用**首帧冻结**（官方参考实现是整段视频逐像素中位数，两者**不等价**），
   相机移动时必须重新评估。
6. BodyHands 数据权利由作者声明为专有；详见 `THIRD_PARTY_NOTICES.md`（含 AGPL-3.0 说明）。
7. **统一模型的 hand 在真实域更保守**（recall 0.4444 @0.25），且缺少带 racket 标注的真实域
   数据来裁决 racket 差异。它现在是**可选路径**，不是默认。
8. 统一模型的训练集里 hand 只抽样了 700 张 BodyHands（外加伪标签与难负样本），
   远少于 hand 专用模型的 1.7 万张——这是它 hand 偏弱的结构性原因，需要下一轮改数据配比。

## 12. 版本历史

| 版本 | 检测模型 | 关键变化 |
| --- | --- | --- |
| V2.1 | `hand_yolov8n_gray_interface_v1.onnx`（640） | 首次冻结接口；hand 在本域不出框 |
| V2.2 | `hand_yolov8n_gray_final_v2_960.onnx`（960） | 换 BodyHands 960 + 每模型独立 imgsz |
| V2.3 | `hand_yolov8n_gray_final_v3_960.onnx`（960） | pseudo-label 微调，P/R/F1/AP50 全面提升 |
| **V2.4** | **+ `pingpong_yolov8n_gray_3cls_960.onnx`（960，统一三类）** | **一次推理出 hand+racket；默认仍用分离模型，统一模型 `-Unified` 打开** |
