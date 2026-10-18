# C 端感知 —— 队长联调包（C_ACTUAL_INTERFACE_V2_3）

## 1. 先跑起来（30 秒）

1. 把 ZIP 解压到一个**纯英文路径**目录（例如 `D:\c_iface`）
2. 打开 PowerShell，`cd` 到解压出来的目录
3. 执行：

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1
```

4. 看结果：

- `out\result_image.jsonl`、`out\result_video.jsonl` —— 每帧一行 JSON
- `out\overlay_image.png`、`out\overlay_video.mp4` —— 画了 ball 中心 / hand 框 / racket 框

`run_demo.ps1` 会先用 `examples\` 里的样例图跑一次，再用样例视频跑一次。
模型文件缺失时会明确打印 `MISSING_MODEL` 并以退出码 2 结束，不会抛异常。

> **为什么必须用英文路径**：Windows PowerShell 5.1 在向原生 .exe 传参时会把非 ASCII
> 字符弄坏（引擎本身支持 UTF-8 中文路径，但 5.1 的传参层不行）。用 PowerShell 7+ 可避免。

## 2. 跑你自己的视频

```powershell
.\bin\c_perception_cli.exe `
  --video 你的视频.mp4 `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray_final_v3_960.onnx `
  --racket-model models\racket_yolov8n_gray.onnx `
  --config config\inference.yaml `
  --output out\result.jsonl `
  --overlay out\overlay.mp4
```

单张图：

```powershell
.\bin\c_perception_cli.exe --image 你的图.png `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray_final_v3_960.onnx `
  --racket-model models\racket_yolov8n_gray.onnx
```

只检查模型能否加载：

```powershell
.\bin\c_perception_cli.exe --self-test --image examples\sample_frame.png `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray_final_v3_960.onnx `
  --racket-model models\racket_yolov8n_gray.onnx
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

| 检测器 | 输入尺寸 | 来源 |
| --- | --- | --- |
| hand | **960 × 960** | 从 hand ONNX 的 input shape 自动读取 |
| racket | **640 × 640** | 从 racket ONNX 的 input shape 自动读取 |
| ball | 512 × 288 | BallTrack 官方契约，15 通道 gray3 |

hand 与 racket **同时工作、互不影响**。配置里**没有** `imgsz` 键，不需要你填。

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

## 8. hand 成绩（如实）

评测集：`BNDSTT_MANUAL_GT_V1`，**41 图 / 54 个 hand box**，来自 **5 个 session**，
conf = 0.25。

| 指标 | V2.2（旧 hand） | **V2.3（本包）** |
| --- | --- | --- |
| Precision | 0.3626 | **0.4023** |
| Recall | 0.6111 | **0.6481** |
| F1 | 0.4552 | **0.4965** |
| AP50 | 0.3789 | **0.4670** |
| TP/FP/FN | 33/58/21 | **35/52/19** |

**请勿外推。** 只有 41 张图、54 个框、单次测量。可信的是**方向**（精确率与召回率
同时上升），**不是**这些数字对其他球场、光照、机位或球员服装的泛化能力。

历史（说明为什么换模型）：

- V1 = Ultralytics hand-keypoints 640：在本域 **Recall = 0**（完全检不到）
- V2 = BodyHands 960：Recall 0.6111
- V3 = BodyHands + 乒乓球域 pseudo-label 微调：Recall 0.6481

`hand_conf` 固定 **0.25**，**没有用评测集调阈值**；checkpoint 按 BodyHands 验证集选择，
**没有用评测集挑 epoch**。

## 9. 当前速度说明

CPU 三模型串行，1920×1080 约 **1.8–1.9 s/帧**（hand 960 是主要成本；
V2.1 的 640 hand 约 0.66 s/帧）。

> **这是功能联调参考实现，不是实时目标。**
> 60 FPS 与 RK3576/NPU 加速属于后续板端工作。

## 10. 依赖

- Microsoft Visual C++ 2015-2022 运行库（x64）
- `bin/` 里已带 `onnxruntime.dll`、`opencv_world4100.dll`、
  `opencv_videoio_ffmpeg4100_64.dll`
- **不需要** CUDA、**不需要** Python、**不需要**自己编译
- 仅当使用第 7 节的可选时序工具时才需要 Python

## 11. 已知限制（如实）

1. hand 成绩是小样本单次测量（41 图 / 54 框 / 5 session），**不代表泛化**。
2. **CPU 非实时**：约 1.8–1.9 s/帧。
3. **未做 RKNN 转换、未上板、无 NPU 实测**；`BOARD VERIFIED = NO`。
4. **未接真实 OV9281 相机**：灰度链路在公开数据与解码视频帧上验证。
5. BallTrack 背景用**首帧冻结**（官方参考实现是整段视频逐像素中位数，两者**不等价**），
   相机移动时必须重新评估。
6. BodyHands 数据权利由作者声明为专有；详见 `THIRD_PARTY_NOTICES.md`（含 AGPL-3.0 说明）。

## 12. 版本历史

| 版本 | hand 模型 | 关键变化 |
| --- | --- | --- |
| V2.1 | `hand_yolov8n_gray_interface_v1.onnx`（640） | 首次冻结接口；hand 在本域不出框 |
| V2.2 | `hand_yolov8n_gray_final_v2_960.onnx`（960） | 换 BodyHands 960 + 每模型独立 imgsz |
| **V2.3** | **`hand_yolov8n_gray_final_v3_960.onnx`（960）** | **pseudo-label 微调，P/R/F1/AP50 全面提升** |
