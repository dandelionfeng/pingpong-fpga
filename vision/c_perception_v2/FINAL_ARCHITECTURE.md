# C 端感知 V2 — FINAL ARCHITECTURE（HANDOFF V2 修订版）

冻结日期：2026-10-15。本文件取代 HANDOFF V1 的架构描述。

## 修订原因（队长反馈）

1. **hand 必须是真实 bbox**，不能只给 wrist 关键点 —— B 的离手逻辑要用 `ball ↔ hand bbox`。
2. **BallTrack 必须吃灰度**：A 端真实输入是 **GRAY8**，不是彩色 BGR/RGB。
3. 需要**队长本机可直接调用的 C++ 程序**。

## 架构总览

```text
输入：GRAY8 (CV_8UC1)，单通道 uint8
  ↓  C 内部统一做 gray3 = GRAY8 复制到 3 通道
  ├─ BALL   : RacketVision BallTrack (TrackNetV3, 官方 pretrained, READ-ONLY)
  │           时序输入，官方窗口 = median + center 前 4 帧
  │           输出 heatmap → 阈值 0.5 → 连通域 → 连通域中心（原图坐标）
  │           + causal Kalman 轨迹连续性
  ├─ HAND   : YOLOv8n 1 类 hand bbox detector（gray3 训练）
  ├─ RACKET : YOLOv8n racket detector（gray3）
  └─ POSE   : yolov8n-pose.pt —— OPTIONAL / LEGACY DIAGNOSTIC，不再是必需运行时模型
```

随后由 **B** 负责：hand role association（持拍手 / 抛球手）→ release → apex → contact
→ 3D trajectory → toss height → legal / illegal。

> **C 不判断发球合法与否。C 也不判断 hand 角色。**
> C 只输出画面里所有清楚可见的 hand bbox；哪只手是抛球手、哪只是持拍手，需要时序与状态机，属于 B。

## 关键不变式

1. **HAND 必须是真实 YOLO hand bbox**。绝对禁止用 wrist 周围固定方框冒充 hand。
2. **所有坐标是 original GRAY8 image coordinates**，不是 640 letterbox 坐标。
3. **Pose 不是必需依赖**：不运行 Pose 时，ball / hand / racket 输出必须完整成立。
4. **代码不写死图像尺寸**；使用真实输入尺寸。
5. **temporal 三态严格区分**：
   - `DETECTED`：本帧有 detector candidate 且被 track 接受 → **算检测到**；
   - `RECOVERED_LOW_CONF`：本帧**确实存在** candidate（base_conf ≤ conf < 工作阈值）
     且通过运动 gate → 算低置信恢复；
   - `PREDICTED_ONLY`：本帧**没有**被接受的 candidate，只有 Kalman 预测 →
     **不是 detection**，只能用于轨迹连续性。
6. association 只能是 `HEURISTIC` / `UNKNOWN`。

## BallTrack 官方输入契约（从官方源码核实，非推测）

| 项 | 值 | 来源 |
| --- | --- | --- |
| seq_len | 4 | `configs/tracknetv3_base.py` |
| 输入分辨率 | 512 × 288 | 同上 |
| bg_mode | `concat` | 同上 |
| last_only | true | 同上 |
| 输入张量 | `[1, 15, 288, 512]` | 导出的 ONNX |
| 15 通道构成 | `median(3) + f(i-4)(3) + f(i-3)(3) + f(i-2)(3) + f(i-1)(3)` | `inference.py` 的 `concat([median, moveaxis(seq,-1,1)],0)` |
| 预测对齐 | 第 i 帧的预测使用 **i-4..i-1** 帧 | `fids = range(i-seq_len, i)` |
| 输出张量 | `[1, 1, 288, 512]` | `last_only=True` 裁掉其它 3 张 |
| 解码 | 阈值 0.5 → 连通域 → 最大外接矩形 → 矩形内热图均值作 confidence | `_predict_location` |
| 坐标回原图 | `center * (orig_w/512, orig_h/288)` | `inference.py` |

**gray3 的正确做法**：上述 5 个组成部分（median + 4 帧）**每一个都是不同的灰度帧复制成 3 通道**，
不是"某一帧复制 15 次"。测量确认：C++ 实现与官方 Python 逐帧一致（见 parity 报告）。

## Ball 后端选择（gray3 真实部署输入下的重测）

评测集：`BNDSTT_MANUAL_GT_V1` 中 36 帧含球人工 GT（只读）。

| 指标 | BallTrack COLOR | **BallTrack GRAY3** | YOLO GRAY3 |
| --- | --- | --- | --- |
| detection presence | 24/36 | **28/36** | 34/36 |
| center error ≤ 50 px | 24/36 | **28/36** | 10/36 |
| center error median | 8.09 px | **7.96 px** | 182.41 px |
| center error P90 | 29.00 px | **24.86 px** | 844.83 px |

**FINAL BALL = BALLTRACK**。

⚠️ **为什么不能只看 presence**：YOLO gray3 报告 34/36 检出，但其中 **17 帧中心误差 > 200 px**
（最高 1304 px），置信度最高到 0.54 —— 是**高置信误检**。按"定位正确"口径，
BallTrack gray3 28/36 对 YOLO 10/36；逐帧对比中 BallTrack 独对 **19 帧**，YOLO 独对 **1 帧**。

**重要正面结论**：BallTrack 在灰度下**比彩色更好**（24/36 → 28/36），
说明它不是"偷偷吃彩色"才有效 —— 灰度部署反而更贴合它的训练分布。

## Hand 检测器

| 项 | 值 |
| --- | --- |
| 数据 | Ultralytics 官方 **hand-keypoints**（`hand-keypoints.zip`，AGPL-3.0） |
| 图/标签 | 26,768 图 / 26,768 标签（train 18,776 + val 7,992） |
| bbox 来源 | **数据集自带的 bbox 字段（第 1..4 列）**，**不是**从 21 个关键点推导 |
| 类 | `0 = hand`（单一类，不区分 toss/racket/left/right） |
| 输入 | gray3（BGR→GRAY8→复制 3 通道），标签坐标不变 |
| 模型 | YOLOv8n 1 类 |
| 配方 | imgsz 640, epochs 100, patience 20, batch 16, seed 42, device 0, amp |
| 域内评测 | `BNDSTT_MANUAL_GT_V1` 的 hand GT **只读** |

## Racket 检测器

| 项 | 值 |
| --- | --- |
| 模型 | YOLOv8n（公开 tableTennis v2，类 `0 ball / 1 racket`） |
| 彩色参考 | racket AP50 = 0.8127 |
| gray3 实测 | racket AP50 = 0.6998（**跌 0.1129 > 0.05 阈值**） |
| 处置 | 触发 **一次性灰度适配 fine-tune**（60 epochs, patience 15，从现有 best.pt 出发） |

## Pose / wrist 状态变更

`yolov8n-pose.pt` **保留代码，但不再是 FINAL REQUIRED RUNTIME MODEL**。
状态：**OPTIONAL / LEGACY DIAGNOSTIC**。

原因：队长正式接口需要 hand bbox，不是 wrist。
正式 C++ runtime **不依赖 Pose**；如果 B 之后想额外用 wrist，接口保留。

## 部署产物

- C++17 ONNX Runtime 引擎：`software/pc_pipeline/modules/c_actual/`
- CLI：`c_perception_cli.exe`（`--image` / `--video`，输入 GRAY8，内部 gray3）
- 交付包：`artifacts/handoff/C_PERCEPTION_HANDOFF_V2/`（模型 + exe + 配置 + demo）
- 模型清单：`vision/c_perception_v2/MODEL_MANIFEST.md`
- ONNX parity：`artifacts/files/reports/ONNX_EXPORT_V1/ONNX_PARITY_REPORT.md`
- C++/Python parity：`artifacts/files/reports/C_CPP_PARITY/parity_report.json`
- RKNN：`vision/c_perception_v2/RKNN_DEPLOYMENT_GUIDE.md`（仍未上板）
