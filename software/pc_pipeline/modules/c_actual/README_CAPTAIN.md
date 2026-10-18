# C 端感知 —— 队长联调包（C_ACTUAL_INTERFACE_V2_2）

## 1. 先跑起来（30 秒）

1. 把 ZIP 解压到一个**英文路径**目录（例如 `D:\c_iface`）
2. 打开 PowerShell，`cd` 到解压出来的目录
3. 执行：

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1
```

4. 看结果：

- `out\result_image.jsonl`、`out\result_video.jsonl` —— 每帧一行 JSON
- `out\overlay_image.png`、`out\overlay_video.mp4` —— 画了 ball 中心 / hand 框 / racket 框

`run_demo.ps1` 会先用 `examples\` 里的样例图跑一次，再用样例视频跑一次。
模型文件缺失时会明确打印 `MISSING_MODEL`，不会抛异常。

## 2. 跑你自己的视频

```powershell
.\bin\c_perception_cli.exe `
  --video 你的视频.mp4 `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray_final_v2_960.onnx `
  --racket-model models\racket_yolov8n_gray.onnx `
  --config config\inference.yaml `
  --output out\result.jsonl `
  --overlay out\overlay.mp4
```

单张图：

```powershell
.\bin\c_perception_cli.exe --image 你的图.png `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray_final_v2_960.onnx `
  --racket-model models\racket_yolov8n_gray.onnx
```

只检查模型能否加载：

```powershell
.\bin\c_perception_cli.exe --self-test --image examples\sample_frame.png `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray_final_v2_960.onnx `
  --racket-model models\racket_yolov8n_gray.onnx
```

## 3. 输入是什么

**你只需要给单通道 8 位灰度图 `GRAY8`（OpenCV `CV_8UC1`），原图尺寸。**

引擎内部自己完成 gray3、letterbox、归一化、NMS、坐标还原。
**你不需要**自己做这些。

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
  "hands":   [ { "class": "hand",   "confidence": 0.91, "bbox": [700.0, 360.0, 95.0, 82.0] } ],
  "rackets": [ { "class": "racket", "confidence": 0.86, "bbox": [1010.0, 340.0, 120.0, 145.0] } ],
  "infer_ms": 660.0
}
```

坐标全部是**原图坐标**。

- `ball.state`：`DETECTED` / `WARMUP` / `DROPOUT` / `INVALID`
  - `WARMUP`：BallTrack 是时序模型，前 4 帧没有历史，**没有做预测**，这是正常的
  - 只有 `DETECTED` 才算这一帧看到了球
- `ball.center` 是球心（推荐用这个）；`region` 是热图连通域，**不是球直径**
- `hands` 是**真实 YOLO hand bbox**（不是手腕关键点）

**hand 角色（持拍手 / 抛球手）由 B 判断，C 不判断。**
**trajectory / Kalman / 合法性也由 B 负责。**

## 5. 接进项目（SDK）

`bin/` 里是可执行 demo；`sdk/` 里是给 C++ 集成的接口：

```
sdk/include/c_perception_engine.hpp   # CPerceptionEngine 头文件
sdk/lib/c_actual.lib                  # 静态库
```

也可以直接用仓库里的 `DetectorBackend` 桥接（源码在仓库
`software/pc_pipeline/modules/c_actual/src/detector_backend_c_actual.cpp`）：

```cpp
DetectorContext ctx;      // ctx.gray 是 CV_8UC1 GRAY8
ctx.meta = ...; ctx.eye = Eye::Left;
DetectionResult r = detector->infer(ctx, stop, timeoutMs);
// r.boxes 就是上面第 4 节的 schema
```

## 6. 接口已冻结

**接口冻结，后续只换权重。** 详见 `INTERFACE_CONTRACT.md`：
输入类型、输出类别、JSON 字段、坐标空间、C++ API 签名都不会再变。

## 7. 当前速度说明

PC 端 CPU 三模型串行约 **660 ms/帧**（1920×1080）。

> **这是功能联调参考实现，不是实时目标。**
> 60 FPS 与 RK3576/NPU 加速属于后续板端工作。

## 8. 依赖

- Microsoft Visual C++ 2015-2022 运行库（x64）
- `bin/` 里已带 `onnxruntime.dll`、`opencv_world4100.dll`、`opencv_videoio_ffmpeg4100_64.dll`
- **不需要** CUDA、**不需要** Python、**不需要**自己编译

## 9. 已知限制（如实说明）

1. **hand 模型是 INTERFACE_V1 冻结版**，训练未跑满全部 epoch。
   精度不是本次目标；换更好的权重只需替换 `hand_yolov8n_gray_final_v2_960.onnx`，
   **接口不变**。
2. **BallTrack 背景帧用首帧**（online approximation）。官方参考实现用整段视频
   逐像素中位数，两者**不等价**。固定机位下可用；**相机移动时必须重新评估**。
3. **每帧约 660 ms**，未做实时优化。
4. **未做 RKNN 转换、未上板**。
5. `--cuda` 存在，默认走 CPU。

## 10. hand 域差异 —— 必须知道的真实情况

**hand detector 本身是好的，推理链也是对的。但它在乒乓球域分数偏低。**

实测（同一个 INTERFACE_V1 模型，同一套灰度预处理）：

| 输入 | hand 最高分 |
| --- | --- |
| 它自己的 val 图（近距离手部，224×224） | **0.75 – 0.94** |
| BNDSTT 乒乓球域（远距离手，33–85 px） | **0.0014 – 0.12** |

结论：

- 模型能加载、能推理、能输出真实 bbox —— **代码与接口没有问题**；
- 但在乒乓球域的分数**低于 `hand.conf = 0.25`**，所以 demo 视频里 `hands` 为空；
- 同一帧 `racket` 模型得 **0.77** 分，说明预处理、通道、坐标链路全部正常；
- 根因是**训练数据的域差异**：官方 hand-keypoints 是近距离、竖构图的手部特写，
  部署场景是远距离球场俯视图。

**处理方式（明确）：**

- ❌ **不会**为了「让 hand 有输出」而降低阈值 —— 那会产出大量假 hand 框，
  违反「不得伪造 hand bbox」的要求；
- ✅ hand 训练仍在继续（冻结时约 epoch 23，在它**自己的域**上 best mAP50 0.979）；
- ✅ **换权重不需要改接口**：训练完成后只替换
  `models/hand_yolov8n_gray_final_v2_960.onnx`，输入/输出/类别/C++ API 全部不变；
- ⚠️ 用域内数据改善 hand 属于**非阻塞的下一阶段**，不影响现在把接口交给 B 联调。

**这对联调意味着**：ball 与 racket 已有真实输出（样例视频 40 帧里 ball 检出 **29** 帧、
racket 28 个框），**hand 目前在本域几乎不输出**。
B 可以先接上接口打通链路；hand 的域内可用性需要后续训练/数据解决。

> 本节的量化证据也记录在
> `artifacts/files/reports/HAND_DOMAIN_GAP_FINDING.json`。

## 11. V2.2 变更（相对 V2.1）

| 项 | V2.1 | **V2.2** |
| --- | --- | --- |
| hand 模型 | `hand_yolov8n_gray_interface_v1.onnx`（640） | **`hand_yolov8n_gray_final_v2_960.onnx`（960）** |
| hand 域内 Recall | 0.0000 | **0.6111** |
| hand 域内 AP50 | 0.0000 | **0.3789** |
| ball / racket | 不变 | **不变** |
| C++ 输入尺寸 | 单一全局 640 | **每个模型从自己的 ONNX input shape 自动读取** |
| 接口 | —— | **完全不变**（GRAY8 进，ball/hand/racket 原图坐标出） |

**重要（实现说明）**：hand 是 960、racket 是 640，两者**各自独立**。引擎在 load 时读取每个 ONNX 的 input shape，据此决定各自的 letterbox 尺寸；任何形状不一致都会在 `warnings` 里明确报错（如 `YOLO_INPUT_CONTRACT_MISMATCH`），**不会静默返回空检测**。