# PR #23 — 建议的标题与正文（供 ChatGPT 更新）

> **给 ChatGPT 的说明**：本机没有 `gh` CLI，且 GitHub API 对私有仓库返回 404，
> 因此无法自动更新 PR #23 的标题与正文。请使用下面的内容更新 **PR #23**
> （**不要新建 PR**，也**不要 merge**）。

---

## 建议标题（二选一，优先第二个）

```
C: finalize ball-hand-racket C++ perception interface
```

备选：

```
C: add captain-facing ball-hand-racket gray3 runtime
```

**为什么必须改**：原标题 `C: finalize ball-racket-wrist perception pipeline`
已经过时 —— wrist 不再是正式接口，hand 现在是真实 bbox 检测器。

---

## 建议正文

```markdown
## 摘要

C 端感知完成 **CAPTAIN INTEGRATION V2.1**：把正式接口从 wrist 修正为
**真实 hand bbox**，修复 BallTrack 灰度输入，并交付队长本机可运行的
C++ 程序与模型包。

**接口已冻结**：后续替换更好的模型权重**不需要改接口**。

---

## P0 修复：BallTrack 输入通道错误

`buildInput()` 之前只构造 **5 个单通道 plane**（`[1,5,288,512]`），
而官方 TrackNetV3 ONNX 要求 **`[1,15,288,512]`**。
结果是**每一次推理都静默失败**，ball 从来没有真正输出过。

修正为官方通道布局：

```
ch  0, 1, 2 = background  R, G, B
ch  3, 4, 5 = f(i-4)      R, G, B
ch  6, 7, 8 = f(i-3)      R, G, B
ch  9,10,11 = f(i-2)      R, G, B
ch 12,13,14 = f(i-1)      R, G, B
```

15 通道 = `median(3) + 4 帧 × 3`，每一项都是**不同的灰度帧复制成 3 通道**，
不是把同一帧复制 15 次。

**效果**：样例视频 ball `DETECTED` 从 **0/40 → 29/40**。

### 硬校验

- `load()` 校验 ONNX 输入必须是 `[batch, 3*(seq_len+1), H, W]`，
  否则报 `BALLTRACK_INPUT_CONTRACT_MISMATCH` 并拒绝加载；
- tensor 尺寸不符时报 `BALLTRACK_TENSOR_SIZE_MISMATCH`，不会带着错误输入运行。

### 时序对齐（无 current-frame leakage）

官方契约 `fids = range(i - seq_len, i)`：第 i 帧用 **i-4..i-1** 预测。
C++ 现在保证：

- frame 1..4 → `WARMUP`（需要 4 帧真实历史，**不复制帧凑历史**）；
- frame 5 是第一个被评分的帧；
- 被评分的当前帧**在推理之后**才进入窗口，因此**永远不会进入自己的输入**。

### 合成测试（确定性，不靠肉眼看图）

- 15 通道逐个断言数值：`[bg(10)|20|30|40|50] × RGB`；
- 断言**尚未见到的下一帧不出现在即将使用的窗口里**。

C++ 引擎单测：**31/31 PASS**。

---

## 接口冻结（C_ACTUAL_INTERFACE_V2_1）

| 项 | 值 |
| --- | --- |
| 输入 | `DetectorContext.gray`，**`CV_8UC1` GRAY8**，原图尺寸（动态，不写死） |
| 输出 | `DetectionResult.boxes`：`ball` / `hand` / `racket`，**原图坐标** |
| ball | **仅真正检出时出现**；`WARMUP`/`DROPOUT`/`INVALID` **不塞假框** |
| hand | **真实 YOLO hand bbox**（不是 wrist，不是 wrist 造的框） |
| hand 角色 | **B 负责**（C 不判断 toss/racket hand） |
| Kalman / trajectory | **B 负责**（C 不输出 `PREDICTED_ONLY` 作为 detection） |
| 合法性 | **C 不判断** |

新增 `INTERFACE_CONTRACT.md` 作为唯一正式接口约定。

---

## 交付物

| 项 | 值 |
| --- | --- |
| 队长包 | `artifacts/handoff/C_PERCEPTION_CAPTAIN_INTEGRATION_V2_1.zip` |
| 大小 / SHA256 | 100.77 MB / `58b07f771359590c7e4f803a9b1142fe863eb6fbae10de7f9f6035cd2e129321` |
| 内容 | `bin/`（exe + 3 DLL）、`models/`（3 ONNX）、`sdk/`（header + 2 lib）、`config/`、`examples/`、README_CAPTAIN.md、INTERFACE_CONTRACT.md、THIRD_PARTY_NOTICES.md |
| 一键 demo | `powershell -ExecutionPolicy Bypass -File run_demo.ps1` —— **实测通过（exit 0）** |
| 旧包 | `C_PERCEPTION_HANDOFF_V2.zip` 已标记 **OBSOLETE_DO_NOT_SEND**（含 5 通道 bug） |

---

## C++/Python parity

同一段视频（BallTrack 真实检出）：

| 项 | 值 |
| --- | --- |
| ONNX 契约 | `[1,15,288,512]` → `[1,1,288,512]` **PASS** |
| ball state 一致 | **40/40** |
| 双方都检出的帧 | **29** |
| center 差异 median | **0.0000 px** |
| center 差异 max | **0.0000 px** |

---

## 诚实记录的发现（未隐藏）

### 1. HAND_DOMAIN_GAP

hand 模型在**它自己的 val 图**上得 **0.75–0.94**，但在**乒乓球域**只有 **0.0014–0.12**，
低于 `hand.conf = 0.25`，因此在样例视频上 `hands` 为空。

- 同一帧 `racket` 模型得 **0.77**，说明预处理、通道、坐标链路全部正常；
- 因此这是**训练数据域差异**，**不是代码 bug**；
- **刻意没有降低阈值**去凑 hand 输出 —— 那会产出假 hand 框，违反「不得伪造 hand bbox」；
- 接口保持冻结，训练完成后**只替换 ONNX 权重即可，无需改代码**。

### 2. BallTrack 背景帧

- 官方参考实现：**整段视频逐像素中位数**；
- 队长面向的在线 C++：**首帧冻结背景**（online approximation）；
- 两者**不等价**。固定机位可用；**相机移动时必须重新评估**。

### 3. 性能

PC CPU 三模型串行约 **660–1830 ms/帧**（1920×1080）。

> **这是功能联调参考实现，不是实时目标。** 60 FPS 与 RK3576/NPU 属于后续板端工作。

---

## 非阻塞的下一阶段

- hand 最终训练与 **BNDSTT 域内 hand 评测**
- threshold refinement
- RKNN 转换（`RKNN_PREPARED_NOT_EXECUTED`）
- AFH03 板端与真实 OV9281 相机验证
- 60 FPS 优化

---

## 测试

| 项 | 结果 |
| --- | --- |
| `python tools/check_repo.py` | **258 tracked files; 0 problem(s)** |
| `python -m pytest -q` | **94 passed** |
| `python -m unittest discover -s tests` | **30 OK** |
| C++ engine tests | **31/31 PASS** |

CI 工作流已修：安装 `pytest pyyaml Pillow`，同时跑 pytest 与 unittest，并把
`manual_annotation_server` 改为**惰性加载**帧清单，使 fresh clone（无 artifacts）
也能 import。

---

## 未做

- 未 merge PR
- 未 force push
- 未重新标注数据
- 未做 RKNN / 未上板
```

---

## 更新后请确认

- PR **#23**（不是新建）
- state 保持 **DRAFT**
- **不要 merge**
- head SHA 应为 **`d92a838afe3a1408bde9ed540f6adbc9547b3832`**
