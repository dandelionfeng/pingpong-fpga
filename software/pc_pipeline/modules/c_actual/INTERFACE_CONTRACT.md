# C 端感知 —— INTERFACE CONTRACT（冻结）

版本：**C_ACTUAL_INTERFACE_V2_1**

本文件是 C 与 A / B 的唯一正式接口约定。**换模型权重不得改变本文件描述的任何内容。**

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
