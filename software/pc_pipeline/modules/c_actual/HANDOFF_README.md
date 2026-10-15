# C 端感知 —— HANDOFF V2（队长可直接运行）

这是 C 模块的正式交付包。**你不需要装 Python，也不需要自己写预处理代码。**

## 30 秒上手

```powershell
# 在本目录下打开 PowerShell
powershell -ExecutionPolicy Bypass -File run_demo.ps1
```

`run_demo.ps1` 会自动：
1. 检查三个模型是否存在（缺哪个就报 `MISSING_MODEL`，不会抛 Python traceback）；
2. 用 `examples/` 里的样例跑一次 `--image`；
3. 如果 `examples/` 里有视频就跑一次 `--video`；
4. 把结果写到 `out/`，并打印每帧的 ball / hand / racket 数量。

## 直接调用 CLI

```powershell
.\bin\c_perception_cli.exe `
  --video serve.mp4 `
  --ball-model   models\balltrack_tracknetv3.onnx `
  --hand-model   models\hand_yolov8n_gray.onnx `
  --racket-model models\racket_yolov8n.onnx `
  --config config\inference.yaml `
  --output result.jsonl `
  --overlay overlay.mp4
```

单张图：

```powershell
.\bin\c_perception_cli.exe --image frame.png `
  --ball-model models\balltrack_tracknetv3.onnx `
  --hand-model models\hand_yolov8n_gray.onnx `
  --racket-model models\racket_yolov8n.onnx
```

只检查模型能不能加载（打印模型信息后退出）：

```powershell
.\bin\c_perception_cli.exe --self-test --image frame.png `
  --ball-model models\balltrack_tracknetv3.onnx `
  --hand-model models\hand_yolov8n_gray.onnx `
  --racket-model models\racket_yolov8n.onnx
```

## 输入约定（重要）

**你只需要给单通道 8 位灰度图 `GRAY8`（OpenCV `CV_8UC1`）。**

引擎内部自己完成：
- `GRAY8` → `gray3`（复制成 3 通道）
- letterbox / resize（每个模型各自的尺寸）
- 归一化
- 后处理 + NMS
- 坐标映射回**原图坐标**

如果你的输入是彩色图/彩色视频，CLI 会**先转成 GRAY8** 再喂给模型 —— 所以 demo 不会"偷偷"用彩色。
这和 OV9281 的真实链路一致。

**你不需要**自己做 gray3、letterbox、normalization。

## 输出

`--output` 写出 JSONL，每行一帧：

```json
{
  "frame_id": 12,
  "timestamp": 0.4,
  "width": 1280,
  "height": 720,
  "ball": {
    "state": "DETECTED",
    "detected": true,
    "confidence": 0.5512,
    "center": [1035.0, 320.0],
    "region": [1016.0, 300.0, 38.0, 40.0],
    "bbox_semantics": "heatmap_component"
  },
  "hands":   [{"class": "hand",   "confidence": 0.71, "bbox": [x, y, w, h]}],
  "rackets": [{"class": "racket", "confidence": 0.64, "bbox": [x, y, w, h]}],
  "infer_ms": 52.3,
  "model_versions": {"ball": "...", "hand": "...", "racket": "..."}
}
```

### ball.state 的四个取值

| state | 含义 | 算不算"检测到球" |
| --- | --- | --- |
| `DETECTED` | 本帧热图超过阈值，连通域解出球心 | **是** |
| `WARMUP` | BallTrack 是时序模型，历史帧还不够（官方窗口 = 前 4 帧） | 否，**没有做预测** |
| `DROPOUT` | 窗口已满但本帧热图低于阈值 | 否 |
| `INVALID` | 出错 | 否 |

> `WARMUP` 期间引擎**不会**复制同一帧来凑历史。前几帧拿不到球是正常的，等窗口满了就有。

### ball bbox 的语义（请务必注意）

BallTrack 本质输出的是**球心**。`region` 是热图连通域的外接框，
标为 `"bbox_semantics": "heatmap_component"`。

**它不是紧凑的球体框**，不要拿它当球直径用。要球位置请用 `center`。
如果只需要 `center`，`region` 可以为 `null`。

### hands

**是真实 YOLO hand bbox**，不是从 wrist 关键点推出来的方框。

引擎输出**画面里所有清楚可见的手**，**不做** toss-hand / racket-hand 角色判断 ——
那需要时序和状态机，属于 B 模块。

## 依赖

`bin/` 里已经带了：
- `onnxruntime.dll`（ONNX Runtime 1.20.1，CPU）
- `opencv_world4100.dll` + `opencv_videoio_ffmpeg4100_64.dll`（OpenCV 4.10.0）

需要 **Microsoft Visual C++ 2015-2022 运行库（x64）**。Windows 10/11 通常已自带；
若提示缺 DLL，装 `vc_redist.x64.exe` 即可。

**不需要** CUDA，**不需要** Python，**不需要** 自己编译。

## 性能

CPU（ONNX Runtime，单帧 1280×720）：

| 阶段 | 说明 |
| --- | --- |
| BallTrack | 时序模型，每次前向覆盖 1 帧 |
| Hand YOLO | 1 类，640×640 |
| Racket YOLO | 640×640 |

CLI 每帧会打印 `infer_ms`。三模型是**串行**跑的。
如果你要更高帧率，可以开多线程分别跑三个模型（本包未做，属 A/B 集成范围）。

## 模型校验

`MODEL_SHA256.txt` 是三个 ONNX 的 SHA256。校验：

```powershell
Get-FileHash models\*.onnx -Algorithm SHA256 | Format-List
```

## 已知限制（如实说明，请勿当成已解决）

1. **BallTrack 的 median 背景**：官方参考实现用整段视频的中位数；C++ 引擎是**在线**的，
   用"已见帧"的运行中位数。三脚架固定机位下两者等价，但**这是一处实现偏差**。
2. **BallTrack 在 clip 开头会 WARMUP**（前 4 帧无输出），这是官方时序契约决定的。
3. **BallTrack 的 ball `region` 不紧凑**，见上文。
4. **RKNN 未转换、未上板**：本包只提供 PC 端 ONNX 推理。板端需要 RKNN Toolkit2 与 AFH03 真机。
5. **未做 CUDA 实测**：`--cuda` 存在但默认走 CPU。

## 目录结构

```text
C_PERCEPTION_HANDOFF_V2/
├── bin/
│   ├── c_perception_cli.exe
│   ├── onnxruntime.dll
│   ├── opencv_world4100.dll
│   └── opencv_videoio_ffmpeg4100_64.dll
├── models/
│   ├── balltrack_tracknetv3.onnx
│   ├── hand_yolov8n_gray.onnx
│   └── racket_yolov8n.onnx
├── config/
│   └── inference.yaml
├── examples/
│   └── （样例图/视频）
├── run_demo.ps1
├── MODEL_SHA256.txt
├── VERSION.txt
└── README.md
```
