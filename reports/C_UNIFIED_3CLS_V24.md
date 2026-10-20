# C：统一三类 YOLO 导出、三类评测、C++ 接入与 V2.4 交付包

日期：2026-10-20　分支：`codex/c-pc-detector`　前一交付：[V2.3](C_CAPTAIN_INTEGRATION_V2_3_DELIVERY.md)

本报告只写实际执行过的检查。模型、数据、C++ 与 ZIP 都在本机真实运行；没有上板、没有 RKNN、
没有真实相机。

---

## 0. 结论先行

1. **统一三类模型已训练完、已导出、已接进 C++、已打包**（`C_PERCEPTION_CAPTAIN_INTEGRATION_V2_4`）。
2. **它现在还不能替代分离模型**：真实目标域 hand 更保守（recall 0.4444 vs 0.6481 @0.25）。
   所以 `run_demo.ps1` 默认走分离模型，统一模型用 `-Unified` 打开。
3. **训练日志里的 `val mAP50 0.7558/0.7623` 不是三类成绩**——验证集里**一个 hand 框都没有**。
   三类评测见第 3 节，hand 用两个独立集单独测。
4. **一个用户前提需要更正**：`best.pt` 现在对应 **epoch 60**（fitness 0.349628），不是 ep54。
   ep54 的 mAP50 确实是 0.7558，但最终被 ep60 覆盖了（见 1.2）。

---

## 1. 训练结果与 best.pt 的真实身份

### 1.1 训练配置（`artifacts/runs/pingpong_3cls_v1/args.yaml`）

| 项 | 值 |
| --- | --- |
| 权重 | `yolov8n.pt` → 类别 0=ball 1=hand 2=racket |
| 输入 / 轮数 / batch | 960 / 60 / 8 |
| 设备 | CPU（本机无可用 CUDA） |
| 耗时 | 38055.3 s（10.6 h），60/60 轮跑满，patience 12 未触发 |
| 数据 | `artifacts/files/datasets/pingpong_3cls_v1`，train 3700 / val 250 |

数据配比（`build_report.json`）：ball 1077、hand 3809、racket 2473 框；背景负样本 320、
难负样本 232、BodyHands 下采样 700 张。`BNDSTT_MANUAL_GT_V1` 的 5 个 session 在建集时**整段排除**。

### 1.2 `best.pt` 到底是哪一轮（与用户前提不一致处）

`best.pt` 与 `last.pt` 内容**完全相同**（SHA256 `543bbde1…5fafa4`），内嵌 metrics 为
`mAP50 0.76226 / mAP50-95 0.30378 / P 0.85834 / R 0.68224`。按 ultralytics 的
`fitness = 0.1·mAP50 + 0.9·mAP50-95` 逐轮算：

| epoch | mAP50 | mAP50-95 | fitness |
| --- | --- | --- | --- |
| 60 | 0.76226 | 0.30378 | **0.349628** |
| **54** | **0.75580** | **0.30405** | 0.349225 |
| 55 | 0.75842 | 0.30348 | 0.348974 |

ep54 的 0.7558 与您给的数字一致，但 ep60 的 fitness 更高，训练结束时 `best.pt` 被 ep60 覆盖。
**当前盘上的 `best.pt` = ep60**。导出用的就是它，没有挑 epoch、没有用评测集调参。

### 1.3 训练验证集的硬缺陷（必须写下来）

val 250 图的标签统计：**ball 233、racket 550、hand 0**。

- 训练日志里的 `all 250 783 0.762 0.304` 以及 `ball 0.691 / racket 0.834` 是**两类**结果。
- 任何"三类 mAP50 = 0.76"的说法都是错的。
- 建集脚本把 BodyHands / 伪标签 / 负样本全放进了 train，val 只来自 tabletennis，所以 hand 天然没验证集。
- 这是**下一轮训练要修的第一件事**（见第 6 节）。

---

## 2. 导出与 PyTorch↔ONNX 一致性

| 项 | 值 |
| --- | --- |
| 权重 | `artifacts/runs/pingpong_3cls_v1/weights/best.pt`（ep60） |
| ONNX | `artifacts/files/models/unified_3cls_v1/pingpong_yolov8n_gray_3cls_960.onnx` |
| 大小 / SHA256 | 12,161,114 B / `10a83aa2a9757d1879da4d72db4c30bd5a42107e374533e015ff92f648609a24` |
| 输入 | `images` `[1,3,960,960]` float32 |
| 输出 | `output0` `[1,7,18900]` = 4 box + 3 class，opset 12，固定 batch |
| 导出命令 | `torch.onnx.export(..., input_names=["images"], output_names=["output0"], opset_version=12, dynamo=False)` |

一致性（12 张 val 图，同一套预处理）：

| 指标 | 值 |
| --- | --- |
| 原始张量最大绝对差 | 4.822e-03（float32 不同算子顺序的正常量级） |
| **解码后框最大坐标差** | **0.0002 px** |
| 框数量差异 | 0 / 未匹配 0 |
| 判定 | **PASS** |

判定标准用的是"解码后的框"而不是原始张量：真正影响下游的是框的像素坐标。

---

## 3. 三类评测（独立评分器，全部实测）

### 3.1 三个评测集，职责不同

| 集 | 规模 | 标注 | 用途 |
| --- | --- | --- | --- |
| `val_3cls` | 250 图 | ball 233 / racket 550 | 训练侧同域 |
| `bodyhands_val` | 1258 图 / 3332 框 | hand（官方 train split 的留出部分） | 公开域 hand |
| `bndstt_manual` | 41 图 / 54 框 / 5 session | hand（人工标注） | **真实目标域 hand** |

`bndstt_manual` 的 5 个 session 在训练数据里被整段排除（伪标签与背景帧都排除），所以它是干净的留出集。

### 3.2 精度表（conf：hand 0.25 / racket 0.30，未用任何评测回调阈值）

| 模型 @ 集 | 类别 | GT | P | R | F1 | AP50(11pt) | AP50(101pt) | AP50-95 | TP/FP/FN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **unified** @ val_3cls | ball | 233 | 0.8011 | 0.6223 | 0.7005 | 0.6659 | 0.6764 | 0.2406 | 145/36/88 |
| **unified** @ val_3cls | racket | 550 | 0.8333 | 0.7818 | 0.8068 | 0.7955 | **0.8192** | 0.3560 | 430/86/120 |
| racket_v1 @ val_3cls | racket | 550 | 0.8028 | 0.7400 | 0.7701 | 0.7428 | 0.7580 | 0.2956 | 407/100/143 |
| **unified** @ bodyhands_val | hand | 3332 | 0.6286 | 0.4988 | 0.5562 | 0.5072 | 0.5140 | 0.2242 | 1662/982/1670 |
| hand_v3 @ bodyhands_val | hand | 3332 | 0.8077 | 0.7260 | 0.7647 | 0.7726 | 0.7921 | 0.4097 | 2419/576/913 |
| **unified** @ bndstt_manual | hand | 54 | **0.6667** | 0.4444 | **0.5333** | **0.4766** | **0.4606** | 0.1725 | 24/12/30 |
| hand_v3 @ bndstt_manual | hand | 54 | 0.4023 | **0.6481** | 0.4965 | 0.4670 | 0.4544 | 0.1548 | 35/52/19 |

### 3.3 评分器可信度：用 V2.3 的数字做回归

用新写的评分器重跑 **hand_v3** 在 `bndstt_manual` 上：P 0.4023 / R 0.6481 / F1 0.4965 /
AP50(11pt) 0.4670 / TP-FP-FN 35-52-19 —— 与 [V2.3 报告](C_CAPTAIN_INTEGRATION_V2_3_DELIVERY.md)
的数字**逐位相同**。所以这张表与历史数字可以横向比较。

（`AP50(11pt)` 是项目历史口径，`AP50(101pt)` 是 COCO/ultralytics 口径；两者都列出来避免口径争议。）

### 3.4 怎么读

- **racket**：唯一有 racket 真值的集合上，统一模型**更好**（0.8192 vs 0.7580）。
- **hand（真实域）**：AP50 略高（0.4766 vs 0.4670），但同一阈值下**更保守**：
  漏 30/54，误检只剩 12。F1 反而更高（0.5333 vs 0.4965）。这是**工作点偏移**，不是排序能力崩掉。
- **hand（公开域）**：统一模型明显更差（0.5140 vs 0.7921）。原因是配比：
  统一集里 hand 只有 700 张 BodyHands + 伪标签，hand 专用模型用了约 1.76 万张。
- **ball**：统一模型的 ball 头**既不输出也不评分**。在 BNDSTT 域样例上它的 ball 最高分只有 0.010，
  完全没有跨域能力——更加说明 ball 必须继续由 BallTrack 提供。

### 3.5 未解决、必须在真人复核时拍板的一件事

同一段 40 帧 BNDSTT 域样例：统一模型 racket 最高分 **0.003**，专用 640 racket 模型最高 **0.806**。
BNDSTT **没有 racket 真值**，所以我只能报告分歧，不能判定谁对：

- 可能统一模型在真实域看不到拍；
- 也可能 640 模型把"手/拍重叠区"当成了拍（样例里 hand 框与 racket 框几乎重合）。

**在拿到带 racket 标注的真实域数据前，不要把 racket 切到统一模型。** 这是本轮明确的阻塞项。

---

## 4. Unified YOLO C++

### 4.1 设计

一个 3 类 ONNX 取代 hand + racket 两个检测器，每帧只做**一次** 960 前向；BallTrack 不动。

- 类别顺序 `0=ball 1=hand 2=racket` 是**模型契约**：加载时用输出通道数（`4+classes`）校验，
  不是 3 类就 `UNIFIED_MODEL_CLASS_MISMATCH` 拒绝加载，**绝不会把 racket 当 hand 输出**。
- 统一图的 **ball 类被有意丢弃**：冻结接口里 ball 只有一个来源（BallTrack），
  两个定义不同的球位置会让 B 无法判断信谁。
- **不传 `--unified-model` 时，行为与 V2.3 完全一致**（分离模型路径原样保留）。

### 4.2 改动文件

| 文件 | 改动 |
| --- | --- |
| `modules/c_actual/include/c_perception_engine.hpp` | `ModelPaths::unified`、`PerceptionResult::unified_model`、`usingUnifiedDetector()`、注释明确 ball 契约 |
| `modules/c_actual/src/internal_onnx.hpp` | `YoloDetector::numClasses()` + `num_classes_` |
| `modules/c_actual/src/yolo_detector_onnx.cpp` | 从输出形状解析类别数 |
| `modules/c_actual/src/perception_engine.cpp` | 统一模型加载 + 类别数校验 + 单次前向分发 hand/racket，丢弃 ball 类 |
| `modules/c_actual/app/c_perception_cli.cpp` | `--unified-model`、模式打印、`model_versions.unified`、非 ASCII 图片路径修复 |
| `modules/c_actual/src/detector_backend_c_actual.cpp` | `CActualConfig::unified_model`、`mode()` = `actual-model-c-actual-v2.4-unified` |
| `modules/c_actual/tests/test_c_actual.cpp` | 新增统一模型测试 + 类别数守卫；端到端测试按交付文件名解析 |
| `modules/c_actual/config/inference.yaml` | V2_4 + `unified:` 段 |
| `modules/c_actual/INTERFACE_CONTRACT.md` | V2_4，新增第 9 节（含兼容性影响表） |
| `modules/c_actual/README_CAPTAIN.md` | V2_4 用法、三类成绩、速度、限制 |
| `modules/c_actual/run_demo.ps1` | `-Unified` 开关；默认分离模型 |

### 4.3 兼容性影响（请 A/B 复核，已写进契约第 9 节）

| 项 | 影响 |
| --- | --- |
| 输入 `CV_8UC1` GRAY8、输出 schema、坐标空间 | **不变** |
| `load/inferGray/reset` 签名 | 不变 |
| `ModelPaths` / `PerceptionResult` | 各新增一个字段（默认空，源码兼容） |
| 每帧 YOLO 前向 | 2 → 1（仅耗时） |
| `DetectorBackend::mode()` | 统一模式多了一个新字符串 **`actual-model-c-actual-v2.4-unified`** |

> **唯一需要 A/B 动作的点**：如果代码里对 `mode()` 做了字符串精确比较（`== "actual-model-c-actual-v2"`），
> 需要改成前缀匹配或同时接受两个值。仓库内 `runner.cpp` 只检查 `mode() == "actual-model"`（bubble 模式），
> 不受影响，但 A/B 的私有分支需要自查。

### 4.4 测试矩阵（全部实际执行）

| 项 | 结果 |
| --- | --- |
| `c_actual_tests.exe`（含模型，分离 + 统一） | **46/46 PASS**，无 SKIP |
| 打包内 `bin\c_actual_tests.exe`（用包内模型） | **46/46 PASS**，无 SKIP |
| 统一模式：只给 ball + unified 即可加载 | PASS |
| 手/racket 都报 960（同一图） | PASS |
| 只输出 hand/racket（ball 类不漏出） | PASS |
| 1 类图冒充统一模型 → 拒绝 + 报错码 | PASS |
| `pytest tests -q` | 94 passed |
| `tools/check_repo.py` | 266 tracked files, **0 problems** |

### 4.5 Python ↔ C++ 一致性（真实帧）

8 帧（1920×1080，样例视频每 5 帧抽 1 帧），C++ 统一模式 vs Python ONNX：

| 指标 | hand | racket |
| --- | --- | --- |
| 框数量 | 8/8 帧一致 | 8/8 帧一致 |
| 逐框最大坐标差 | **0.0004 px** | —（该片段无 racket 框） |
| 判定 | **PASS** | PASS |

同时记录了 C++ 统一模式 vs C++ 分离模型的框数差异（1 vs 3 hand 等），与第 3.4 节的结论一致。
注意：每帧单独跑 CLI，BallTrack 每次都在 WARMUP，所以该一致性只覆盖 hand/racket，不覆盖 ball。

---

## 5. 交付包 V2.4

| 项 | 值 |
| --- | --- |
| 文件 | `artifacts/handoff/C_PERCEPTION_CAPTAIN_INTEGRATION_V2_4.zip` |
| 大小 | 116,250,413 B（110.87 MB），28 个条目 |
| SHA256 | `7edf80ed0ce7a7f475ed7ae7650f3149be02080fde9959a10026f21a3b0156c4` |
| 模型 | balltrack（未变）+ **unified（新增）** + hand_v3（未变）+ racket（未变） |
| 旧包 | V2_1 / V2_2 / V2_3 哈希**未变** |

解压到 `C:\cap_v24final` 后的实跑（非仓库目录）：

| 检查 | 结果 |
| --- | --- |
| `run_demo.ps1`（默认分离） | **exit 0**，image 1 帧 + video 40 帧，hand 66 / racket 28 |
| `run_demo.ps1 -Unified` | **exit 0**，hand 11 / racket 0 |
| `bin\c_actual_tests.exe`（包内模型） | **46/46 PASS** |
| 包内文本文件绝对路径扫描 | 仅 `D:\c_iface` 这种示例路径，无本机路径 |

速度（同一段 40 帧 1920×1080，CPU）：

| 模式 | 本报告两次测量 | 框 |
| --- | --- | --- |
| 分离 | 1532 / 1773–1950 ms/帧 | hand 66 / racket 28 |
| 统一 | 1206 / 1392–1451 ms/帧 | hand 11 / racket 0 |

一次 YOLO 省 18–30%/帧，但 BallTrack 仍是瓶颈，两种模式都远非实时。

---

## 6. 本轮修掉的真实缺陷（都是"跑起来才暴露"）

1. **`run_demo.ps1` 里 `-Unified` 开关与 `$unified` 变量同名**（PowerShell 变量大小写不敏感）
   → 脚本直接崩，解压后 demo 根本跑不起来。已改名 `$unifiedModel`。
2. **CLI 对非 ASCII 图片路径读不了**：`cv::imread` 走 ANSI 代码页，回退分支又用了窄字符
   `std::ifstream`。已改成宽路径 + 字节解码（`openInput()`）。这是真实复现的（中文目录里
   `--image` 直接 exit 5）。
3. **端到端测试写死短文件名** `hand_yolov8n_gray.onnx`，对规范命名的交付包只能 SKIP
   → 已改为按候选名解析，现在 46/46 全跑。
4. 契约/配置/README 的版本号与模型名统一到 V2_4。

---

## 7. 未完成 / 阻塞 / 下一步

**未做（如实）**

- **RKNN 未转换**、无 NPU 实测、**BOARD VERIFIED = NO**。
- **未接真实 OV9281**：灰度链路只在公开数据与解码视频帧上验证。
- **没有带 racket 标注的真实域数据**，所以 3.5 的分歧无法裁决。

**下一轮建议顺序（按性价比）**

1. **补 val 的 hand 真值**：建集时给 BodyHands/伪标签留 ~10% 到 val，否则每次训练都无法自检 hand。
2. **改统一模型配比**：hand 从 700 提到 4000–6000 张 BodyHands，重训 60 轮（CPU 约 10.6 h）。
   目标：`bndstt_manual` recall 至少追平 0.6481 且 precision 不低于 0.40。
3. **补真实域 racket 标注**（哪怕 30–50 框），先把 3.5 的分歧判掉。
4. 追平后再把 `run_demo.ps1` 默认切到 `-Unified`，并做 RKNN INT8 转换（注意 YOLO 前 4 通道
   像素坐标不要量化）。
5. hand 阈值若要调整，必须在**不看 `bndstt_manual`** 的前提下选（例如只在 BodyHands val 上选），
   然后一次性在 `bndstt_manual` 上报数。

---

## 8. 复现命令（本机实际用过）

```powershell
# 1) 导出 + PT/ONNX 一致性（主解释器，无 onnxruntime）
D:\Python\python.exe tmp\export_unified_3cls.py
# 2) ONNX IO 契约 + 解码后一致性（.venv\c-detector，有 onnxruntime 1.31）
.\.venv\c-detector\Scripts\python.exe tmp\verify_unified_onnx.py
# 3) 三类评测（三个集 × 三个模型，约 35 分钟）
.\.venv\c-detector\Scripts\python.exe tmp\eval_3cls.py
# 4) C++ 构建（需 MSVC 环境）
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake --build C:\pp_sdk\build_c_actual
# 5) C++ 测试（模型目录要放在纯英文路径）
$env:C_ACTUAL_MODELS_DIR='C:\pp_models\v23'
$env:C_ACTUAL_MODELS_960_DIR='C:\pp_models\v23'
$env:C_ACTUAL_MODELS_UNIFIED_DIR='C:\pp_models\unified'
C:\pp_sdk\build_c_actual\c_actual_tests.exe
# 6) Python<->C++ 一致性
.\.venv\c-detector\Scripts\python.exe tmp\parity_unified_cpp.py
# 7) 打包 + 解压实跑
D:\Python\python.exe tmp\build_package_v24.py
```

脚本在 `tmp/`（`git ls-files tmp` 为空，**不入库**），实测产物在
`artifacts/files/reports/UNIFIED_3CLS_V1/`：

- `export_report.json`（导出 + PT/ONNX）
- `eval_3cls.json`（三类评测全量，含每类最差样例）
- `parity_cpp_unified.json`（8 帧逐框）

权重与 ONNX 按仓库规则不入库，只留路径、大小与 SHA256（见第 2 节）。
