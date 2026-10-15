# C 端感知 — FINAL HANDOFF V2

> **Supersedes `C_FINAL_HANDOFF_V1.md`.**
>
> 修订原因（队长评审要求）：
> 1. **hand 必须是真实 bbox**，不能只给 wrist keypoint；
> 2. **BallTrack 必须吃灰度**（OV9281 真实输入是 GRAY8）；
> 3. 需要**队长本机可直接调用的 C++ 程序**。

日期：2026-10-15　分支：`codex/c-pc-detector`

未训练**新方法**；未使用人工标注做训练；未修改 quick_test。

---

## A. Final architecture

```text
输入：GRAY8 (CV_8UC1) 单通道 uint8
  ↓  C 内部统一 gray3 = GRAY8 复制 3 通道
  ├─ BALL   : RacketVision BallTrack (TrackNetV3, 官方 pretrained, READ-ONLY)
  ├─ HAND   : YOLOv8n 1 类 hand bbox detector
  ├─ RACKET : YOLOv8n racket detector
  └─ POSE   : OPTIONAL / LEGACY DIAGNOSTIC（不再是必需运行时模型）
```

C **不判断发球合法性**，**也不判断 hand 角色**（toss / racket 属于 B）。

## B. Ball detector decision（gray3 真实部署输入下重测）

评测集：`BNDSTT_MANUAL_GT_V1` 中 36 帧含球人工 GT（**只读**）。

| 指标 | BallTrack COLOR | **BallTrack GRAY3** | YOLO GRAY3 |
| --- | --- | --- | --- |
| detection presence | 24/36 | **28/36** | 34/36 |
| center error ≤ 50 px | 24/36 | **28/36** | 10/36 |
| center error median | 8.09 px | **7.96 px** | 182.41 px |
| center error P90 | 29.00 px | **24.86 px** | 844.83 px |

**FINAL BALL = BALLTRACK。**

**为什么不能只看 presence**：YOLO gray3 的 34/36 里 **17 帧中心误差 > 200 px**
（最高 1304 px，置信度最高 0.54）—— 是高置信误检。按"定位正确"口径
BallTrack 28/36 对 YOLO 10/36；逐帧对比 BallTrack 独对 **19 帧**，YOLO 独对 **1 帧**。

**重要正面结论**：BallTrack 在灰度下**比彩色更好**（24/36 → 28/36），
说明它不是靠彩色信息才有效，灰度部署反而更贴合训练分布。

**未报 precision/FP**：GT 集合只含"有球"帧，无人工确认的负样本。

## C. Hand detector

| 项 | 值 |
| --- | --- |
| 数据 | Ultralytics 官方 **hand-keypoints** |
| 许可 | **AGPL-3.0** |
| 规模 | 26,768 图（train 18,776 / val 7,992） |
| bbox 来源 | **数据集自带 bbox 字段**，**未从关键点推导** |
| 类 | `0 = hand`（单类） |
| 输入 | gray3 |
| 模型 | YOLOv8n，imgsz 640，batch 16，seed 42 |

### 训练状态（如实）

训练进行中，**未跑满 100 epochs**。当前 best checkpoint（epoch 5）在官方 val 上：

| 指标 | 值 |
| --- | --- |
| precision | 0.945 |
| recall | 0.927 |
| **mAP50** | **0.974** |
| mAP50-95 | 0.793 |

⚠️ hand 的 **BNDSTT 域内评测尚未执行**（`hand_domain_contact_sheet` 未生成）。
打包进 handoff 的 `hand_yolov8n_gray.onnx` 是从**当前 best checkpoint** 导出的。

## D. Racket detector（gray3）

| 指标 | COLOR | GRAY3（原模型） | GRAY3（适配后） |
| --- | --- | --- | --- |
| racket AP50 | 0.8127 | 0.6998 | **0.7810** |
| racket P | 0.7628 | 0.8171 | 0.809 |
| racket R | 0.7750 | 0.6063 | 0.730 |
| racket AP50-95 | 0.3435 | 0.2844 | 0.309 |

颜色 → 灰度跌 **0.1129 > 0.05 阈值**，因此执行了**一次性灰度适配 fine-tune**
（60 epochs，patience 15，从原 `best.pt` 出发，标签与 split 不变）。
结果恢复到彩色水平的 **96%**。

## E. Pose / wrist

`yolov8n-pose.pt` 代码保留，状态改为 **OPTIONAL / LEGACY DIAGNOSTIC**。
正式 C++ runtime **不依赖 Pose**。

## F. Public metrics

| | P | R | AP50 | AP50-95 |
| --- | --- | --- | --- | --- |
| ball+racket overall（color） | 0.8152 | 0.7022 | **0.7361** | 0.2986 |
| ball（color） | 0.8676 | 0.6293 | 0.6595 | 0.2536 |
| racket（color） | 0.7628 | 0.7750 | **0.8127** | 0.3435 |
| racket（gray3 适配后） | 0.809 | 0.730 | **0.7810** | 0.309 |

## G. C++ runtime（本轮核心交付）

| 项 | 值 |
| --- | --- |
| 源码目录 | `software/pc_pipeline/modules/c_actual/` |
| 编译器 | MSVC 19.44.35211（VS 2022 Community） |
| 构建 | CMake 3.31.6 + Ninja，**Release 构建成功** |
| 可执行文件 | `c_perception_cli.exe`（140,288 B + 修复后版本） |
| 后端 | ONNX Runtime 1.20.1，**CPU provider 可用**（CUDA 可选） |
| 输入 | **`CV_8UC1` GRAY8**；gray3 / letterbox / normalize 全在引擎内 |
| 输出 | ball（state/center/region/conf）+ hands[] + rackets[]，**原图坐标** |
| CLI | `--image` / `--video` / `--output jsonl` / `--overlay mp4` / `--self-test` |
| 单元测试 | **20/20 PASS**（gray3 契约、letterbox 几何、原图坐标映射、类别感知 NMS、IoU） |

### 本轮修掉的 6 个真实缺陷（都曾导致崩溃或错误结果）

1. **ONNX Runtime 中文路径**：`std::wstring(path.begin(), end())` 按字节扩展会破坏
   非 ASCII 路径 → 改用 `MultiByteToWideChar(CP_UTF8)`。
2. **MSVC `main` 收到 ANSI 参数**：中文路径在进入代码前已损坏（"锟斤拷"）→
   改用 `CommandLineToArgvW` 取 UTF-16 命令行再转 UTF-8。
3. **`std::ofstream` 用 ANSI 代码页**：中文输出路径静默打不开 →
   用 `std::filesystem::path` + 宽字符打开。
4. **`cv::Mat::reshape` 越界**（"Bad new number of rows"）：中位数缓冲尺寸不匹配。
5. **`sort` 沿列排序导致访存跨步 2 MB**：cache 完全失效，1650 ms/帧 →
   改为按行排序 + 预分配缓冲。
6. **ONNX Runtime 会话析构顺序**：进程退出时崩溃（exit 1）→
   引擎析构显式 `release()` 三个 session。

## H. C++/Python parity（**未达 PASS，如实记录**）

| 项 | 值 |
| --- | --- |
| 比较帧数 | 20（公开 test 图合成片段） |
| ball state 一致 | 4/20 |
| ball center 比较 | **0 帧**（该片段两侧都停在 WARMUP/DROPOUT，未产生球心） |
| 匹配框对数 | 32 |
| 坐标差异 median | **0.42 px** |
| 坐标差异 max | **2.65 px** |
| ≤1 px | 26/32 |
| ≤3 px | **32/32** |
| 未匹配检测 | 0 |
| **判定** | **PARTIAL — 不是 PASS** |

**未通过的原因**（已定位，不是坐标系错误）：
两侧使用相同的 letterbox/unletterbox 数学和相同 ONNX 文件，匹配框差异都在亚像素级；
剩余差异是**多个高度重叠候选时 NMS 保留了不同子集**，表现为 **8 帧检测数量不同**
而不是同一目标坐标不同。

**要收口还需**：
1. 让 C++ NMS 的 tie-break 与参考实现完全一致后重跑；
2. 在 BallTrack 真正检出的片段上跑一次，才能比较 ball center。

## I. Model handoff package

| 项 | 值 |
| --- | --- |
| 目录 | `artifacts/handoff/C_PERCEPTION_HANDOFF_V2/` |
| ZIP | `artifacts/handoff/C_PERCEPTION_HANDOFF_V2.zip` |
| 大小 | 100.32 MB |
| 内容 | bin/（exe + 3 DLL）、models/（3 ONNX）、config/、examples/、run_demo.ps1、README.md、MODEL_SHA256.txt、VERSION.txt |

一键 demo：`powershell -ExecutionPolicy Bypass -File run_demo.ps1`
（已验证：image demo + 40 帧 video demo 均 exit 0，产出 JSONL 与 overlay mp4）

## J. ONNX

| 模型 | 文件 | 大小 | parity（对同环境 PyTorch） |
| --- | --- | --- | --- |
| ball | `balltrack_tracknetv3.onnx` | 45,330,200 B | **PASS**（max abs 4.917e-07） |
| hand | `hand_yolov8n_gray.onnx` | 12,116,986 B | 结构正确 |
| racket | `racket_yolov8n.onnx` | 12,117,766 B | 结构正确 |

## K. RKNN

**RKNN_PREPARED_NOT_EXECUTED**。无 toolkit2、无真机。**BOARD VERIFIED = NO**。

## L. Limitations（如实）

1. **hand BNDSTT 域内评测未做**；hand 训练未跑满 100 epochs；
2. **C++/Python parity 为 PARTIAL**（NMS 子集选择差异），见 H 节；
3. **BallTrack 背景帧用首帧**，与官方"整段中位数"有记录偏差；
4. **C++ 每帧耗时 ~660 ms**（1920×1080，三模型串行，CPU）—— 远未到 60 FPS。
   主要成本在 BallTrack 的 15 通道输入组装与 hand 的 letterbox 输入；
   **尚未做板端优化**；
5. **RKNN 未转换、未上板**；
6. 相机曝光策略暂不调整。

## M. B integration schema

C 输出见 `software/pc_pipeline/modules/c_actual/include/c_perception_engine.hpp`。

`legacy DetectionResult.boxes` 恢复正式三类 `ball` / `hand` / `racket`，
JSON 严格用仓库既有 schema：
`{"class": "ball|hand|racket", "confidence": 0..1, "bbox": [x, y, w, h]}`

**HAND 是真实 YOLO hand bbox，绝不用 wrist 造框。**

### DetectorBackend 接入（已实现并编译通过）

`software/pc_pipeline/modules/c_actual/src/detector_backend_c_actual.cpp`
实现 `pipeline::DetectorBackend`，直接调用 `CPerceptionEngine`：

| 项 | 实现 |
| --- | --- |
| `mode()` | `actual-model-c-actual-v2` |
| 输入 | 直接用 `DetectorContext::gray`（已是 `CV_8UC1`），**不做任何转换** |
| 每眼一个引擎 | `left_` / `right_` 两个 `CPerceptionEngine`，BallTrack 历史**不跨相机混用** |
| ball | 输出 `state` / `detected` / `ball_center` / `bbox` / `bbox_semantics` |
| ball bbox 语义 | `heatmap_component`（热图连通域）或 `center_only`（零面积占位）；**不伪造紧凑球框** |
| hand | 真实 YOLO bbox；**不做角色判断** |
| racket | 真实 YOLO bbox |
| `model_version` | `c_actual-v2|balltrack-gray3|hand-yolov8n-gray3|racket-yolov8n-gray3` |
| 模型缺失 | `unavailableCActualDetector(reason)` 返回 `actual-model-unavailable` + 原因，**不让 pipeline 崩溃** |
| 线程安全 | `std::mutex` 保护引擎；`stop`/`timeoutMs` 会被遵守并反映到 `status` |

桥接是**可选构建目标**（默认 OFF，因为它需要 pc_pipeline 的 `nlohmann/json.hpp`）：

```powershell
cmake -S software/pc_pipeline/modules/c_actual -B <build> -G Ninja `
  -DC_ACTUAL_BUILD_PIPELINE_BRIDGE=ON `
  -DC_ACTUAL_PIPELINE_INCLUDE=<repo>/software/pc_pipeline/include `
  -DC_ACTUAL_ONNXRUNTIME_ROOT=<ort> -DC_ACTUAL_OPENCV_ROOT=<opencv> `
  "-DCMAKE_CXX_FLAGS=/I<repo>/third_party"   # nlohmann/json.hpp 位置
```

**已验证编译通过** → `c_actual_pipeline_bridge.lib`（1,660,946 B）。
默认目标 `c_actual.lib` + `c_perception_cli.exe` + `c_actual_tests.exe` 也均构建通过。

## N. A deployment handoff

- 清单与 SHA256：`MODEL_MANIFEST.md`；
- 推理配置：`software/pc_pipeline/modules/c_actual/config/inference.yaml`；
- RKNN 指南：`RKNN_DEPLOYMENT_GUIDE.md`；
- 相机接口目标 1280×720 per eye，代码不写死尺寸。

## O. Reproducibility

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"
& $python -m pytest tests -q
& $python -m unittest discover -s tests
& $python tools/check_repo.py

# C++ 构建（短路径 SDK，见 README）
cmake -S software/pc_pipeline/modules/c_actual -B <build> -G Ninja `
  -DC_ACTUAL_ONNXRUNTIME_ROOT=<ort> -DC_ACTUAL_OPENCV_ROOT=<opencv>
cmake --build <build> --config Release
```

环境：Python 3.12.14，torch 2.5.1+cu121，ultralytics 8.2.82，CUDA 12.1，
RTX 4060 Laptop。**版本未升级。**
C++：MSVC 19.44 + ONNX Runtime 1.20.1 + OpenCV 4.10.0（world）。

---

## 明确未声称的事项

- ❌ 未声称 C++/Python parity PASS（实为 PARTIAL）；
- ❌ 未声称 hand 训练已完成（未跑满 100 epochs，且未做域内评测）；
- ❌ 未声称上板通过 / BOARD VERIFIED；
- ❌ 未声称实时性能达标（实测 ~660 ms/帧）；
- ❌ 未声称 temporal recall 提升。
