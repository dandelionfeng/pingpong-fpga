# C 端感知 —— INTERFACE CONTRACT（冻结）

版本：**C_ACTUAL_INTERFACE_V2_4**

本文件是 C 与 A / B 的唯一正式接口约定。**换模型权重不得改变本文件描述的任何内容。**

V2.4 相对 V2.3 **只增加一条可选模型路径**（见第 9 节：一个 3 类 ONNX 同时给 hand 与
racket）。不传该模型时，引擎行为与 V2.3 完全一致；输入的 GRAY8、输出类别、JSON 字段、
坐标空间、C++ API 签名全部未变。

---

## 1. 输入

| 项 | 值 |
| --- | --- |
| 字段 | `DetectorContext.gray`（也支持 standalone `CPerceptionEngine::inferGray`） |
| 类型 | **`CV_8UC1`**，单通道 8 位灰度（GRAY8） |
| 内容 | **original eye image**，即 A 端直接给的那一帧 |
| 尺寸 | **动态读取**。实际目标是 1280×720 per eye；代码**不写死尺寸** |
| 不支持 | 彩色 BGR/BGR、float、16 位、多通道 |

调用方**不需要**自己做：`gray3`、`resize`、`letterbox`、`normalize`、`NMS`、坐标还原。
**这些全部由 C 内部完成。**

如果传入非 `CV_8UC1`，调用会**明确报错**，不会静默跑错。

---

## 2. 输出

`DetectionResult.boxes`（JSON array）。坐标一律是 **original eye pixel coordinates**。

### ball

**只有 BallTrack 在本帧真正检出时才出现。**
`WARMUP` / `DROPOUT` / `INVALID` 时 **`boxes` 里没有 ball 条目** —— 不会塞零面积假框。

```json
{
  "class": "ball",
  "confidence": 0.78,
  "bbox": [820.0, 312.0, 18.0, 17.0],
  "center": [829.0, 320.5],
  "bbox_semantics": "heatmap_component",
  "state": "DETECTED",
  "detected": true,
  "detector": "balltrack"
}
```

- `bbox` 是 **BallTrack 热图连通域的外接框**，语义为 `heatmap_component`。
  **它不是球直径**，也不是围绕球心造的固定框。
- **新代码请优先读 `center`**（球心，canonical output）。
- 旧代码只读 `bbox` 仍可工作。

### hand

**真实 YOLO hand bbox**，画面里所有超过阈值的可见手都会输出。

```json
{ "class": "hand", "confidence": 0.91, "bbox": [700.0, 360.0, 95.0, 82.0] }
```

- 不是 wrist keypoint，不是 wrist 周围造的框。
- **C 不判断 hand 角色**：没有 `toss_hand` / `racket_hand` / `left_hand` / `right_hand`。

### racket

```json
{ "class": "racket", "confidence": 0.86, "bbox": [1010.0, 340.0, 120.0, 145.0] }
```

---

## 3. 一次完整输出示例

```json
{
  "boxes": [
    {
      "class": "ball",
      "confidence": 0.78,
      "bbox": [820.0, 312.0, 18.0, 17.0],
      "center": [829.0, 320.5],
      "bbox_semantics": "heatmap_component"
    },
    { "class": "hand", "confidence": 0.91, "bbox": [700.0, 360.0, 95.0, 82.0] },
    { "class": "hand", "confidence": 0.88, "bbox": [930.0, 350.0, 90.0, 80.0] },
    { "class": "racket", "confidence": 0.86, "bbox": [1010.0, 340.0, 120.0, 145.0] }
  ]
}
```

**没有 ball detection 时，数组里就没有 ball 条目**（可能只有 hand / racket，或为空数组）。

---

## 4. 职责边界（重要）

| 谁 | 负责 |
| --- | --- |
| **C** | ball / hand / racket 的单帧 observation，原图坐标 |
| **B** | hand 角色（持拍手 / 抛球手）、离手、触拍、球心精修、三维、trajectory、Kalman、事件、合法/非法判定 |
| **A** | 采集、GRAY8 交付、时序帧号 |

- **C 不做 hand role association。**
- **C 不做 Kalman / trajectory。**
- **C 不判断发球合法性。**
- `PREDICTED_ONLY` 之类的纯预测点**永远不会**作为 detector observation 出现在 `boxes` 里。

---

## 5. ball state 语义

| state | 含义 | boxes 里有 ball 吗 |
| --- | --- | --- |
| `DETECTED` | 本帧热图过阈值，解出球心 | **有** |
| `WARMUP` | BallTrack 是时序模型，历史帧还不够（需要前 4 帧） | 无 |
| `DROPOUT` | 窗口已满但本帧热图低于阈值 | 无 |
| `INVALID` | 出错或模型未加载 | 无 |

`WARMUP` 期间引擎**不会复制同一帧来凑历史**。前 4 帧拿不到球是正常的。

---

## 6. 生命周期

- `CPerceptionEngine::load(paths, config, error)` —— 加载三个 ONNX。
- `inferGray(gray, meta)` —— 一帧进，一帧结果出。
- `reset()` —— **切换视频 / clip / 相机重启时必须调用**：清空时序历史、冻结背景、帧计数。
- **左眼与右眼使用两个独立引擎**，历史绝不混用。

---

## 7. 接口冻结承诺

以下内容**已冻结**，后续替换更好的模型权重时**不得修改**：

- 输入类型（`CV_8UC1` GRAY8）与尺寸处理方式（动态）
- 输出类别（`ball` / `hand` / `racket`）
- 输出 JSON schema（上面各字段名）
- 坐标空间（original eye pixels）
- C++ API 签名（`load` / `inferGray` / `reset`）
- `DetectorBackend::infer(context, stop, timeoutMs)` 与 `mode()`

## 8. 各检测器的输入尺寸（V2.4）

默认交付走**统一三类模型**：hand 与 racket 来自同一个 960×960 图，每帧只跑一次 YOLO。
分离模型路径（V2.3 legacy）仍保留，两者使用**不同的**输入分辨率，各自从**自己的 ONNX
input shape** 读取：

| 模式 | 检测器 | 输入尺寸 |
| --- | --- | --- |
| 统一（默认） | unified（hand + racket 一次前向） | **960 × 960** |
| 统一（默认） | ball (BallTrack) | 512 × 288（官方 TrackNetV3 契约，固定） |
| 分离（legacy） | hand | **960 × 960** |
| 分离（legacy） | racket | **640 × 640** |
| 两种模式 | ball (BallTrack) | 512 × 288（官方 TrackNetV3 契约，固定） |

调用方**不需要**关心这些数字，也不需要在配置里指定。若某个 ONNX 的输入形状与引擎构造的张量不一致，结果会在 `warnings` 中出现 `YOLO_INPUT_CONTRACT_MISMATCH` / `YOLO_TENSOR_SIZE_MISMATCH` / `YOLO_INFERENCE_FAILED` 等明确错误，**绝不会静默返回空检测**。

---

## 9. 统一三类模型（V2.4 新增，可选）

一个 ONNX 同时输出 hand 与 racket，每帧只做 **一次** YOLO 前向。用途：板端 NPU 只需
一个检测模型，部署与量化都少一半。

### 9.1 类别顺序是契约

```
0 = ball     1 = hand     2 = racket
```

加载时用 ONNX 的输出通道数（`4 + classes`）校验。若不是 3 类，`load()` 直接失败并返回
`UNIFIED_MODEL_CLASS_MISMATCH`。**绝不会把 racket 类当 hand 输出。**

### 9.2 输出仍然是 `ball` / `hand` / `racket`

- `hands` 只放 `hand` 类的框（阈值 `hand_conf`，默认 0.25）
- `rackets` 只放 `racket` 类的框（阈值 `racket_conf`，默认 0.30）
- **`ball` 类被丢弃，不进 `boxes`**：冻结接口里 ball 的唯一来源是 BallTrack。
  一个 YOLO ball 框与 BallTrack 的热图球心定义不同，同时输出会让 B 拿到两个互相竞争的
  球位置。这是有意为之，不是漏实现。

### 9.3 兼容性影响（供 A / B 技术复核）

| 项 | 影响 |
| --- | --- |
| 输入 `CV_8UC1` GRAY8 | 不变 |
| 输出类别与 JSON schema | 不变（`model_versions` 增加一个可选 `unified` 字段） |
| 坐标空间 | 不变（original eye pixels） |
| `CPerceptionEngine::load/inferGray/reset` | 签名不变；`ModelPaths` 新增 `unified` 字段（默认空） |
| `PerceptionResult` | 新增 `unified_model` 字段（默认空）；`hand_model`/`racket_model` 在统一模式下都指向同一图 |
| 每帧 YOLO 前向次数 | 2 → 1（只影响耗时，不影响语义） |
| `DetectorBackend::mode()` | 统一模式返回 `actual-model-c-actual-v2.4-unified`；分离模式仍是 `actual-model-c-actual-v2` |

**如果 A/B 的代码按 `mode()` 字符串精确匹配 `actual-model-c-actual-v2`，需要改成前缀匹配
或同时接受两个值。** 这一点请在评审时确认。
