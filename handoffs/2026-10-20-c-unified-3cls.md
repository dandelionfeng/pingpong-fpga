# 任务交接

- 任务编号/负责人：C-2026-10-20 统一三类 YOLO 交付 / 蒲公英（C 角色，agent 执行）
- 基准提交号/工作分支：基准 `aebf270`（`codex/c-pc-detector`），本轮提交见 `git log -1`
- 当前目标与不包含的范围：
  - 目标：把统一三类 YOLO（ball=0/hand=1/racket=2）导出为 ONNX、做三类独立评测、接进 C++ 引擎
    与 CLI、打包 V2.4 并在 ASCII 目录解压实跑验证。
  - 不包含：RKNN 转换、NPU/上板实测、真实 OV9281 采集、重训、阈值调优、
    `run_demo.ps1` 默认切到统一模型（结论是"暂时不切"）。
- 允许修改的文件：`software/pc_pipeline/modules/c_actual/**`（引擎/CLI/后端/tests/config/契约/README/demo 脚本）、
  `reports/C_UNIFIED_3CLS_V24.md`、本文件。未改 A/B 的任何源码、规划、Word 或他人分支文件。
- 输入输出/依赖的接口版本：`C_ACTUAL_INTERFACE_V2_4`（输入 GRAY8、输出 ball/hand/racket 原图坐标、
  `load/inferGray/reset` 签名均**未变**）。统一模式多了一个 `mode()` 值
  `actual-model-c-actual-v2.4-unified`，需 A/B 自查是否有字符串精确比较。
- 环境与复现命令：
  - 训练/导出：`D:\Python\python.exe`（ultralytics 8.4.175 / torch 2.10 CPU）
  - ONNX 校验与评测：`.\.venv\c-detector\Scripts\python.exe`（onnxruntime 1.31 / cv2 4.10 / torch 2.5.1）
  - C++：MSVC 19.44 + CMake/Ninja，`cmake --build C:\pp_sdk\build_c_actual`（需先 vcvars64）
  - 完整命令见 `reports/C_UNIFIED_3CLS_V24.md` 第 8 节；脚本在 `tmp/`（不入库）。
- 已执行检查及真实结果：
  - 训练：60/60 轮跑完（38055 s，CPU）；`best.pt`＝**ep60**（fitness 0.349628），非用户说的 ep54。
  - 导出：`pingpong_yolov8n_gray_3cls_960.onnx`，12,161,114 B，
    SHA256 `10a83aa2…609a24`，`[1,3,960,960] → [1,7,18900]`；PT↔ONNX 解码后最大差 **0.0002 px**。
  - 三类评测：unified@bndstt_manual hand P 0.6667 / R 0.4444 / F1 0.5333 / AP50 0.4606（24/12/30）；
    hand_v3 同集 P 0.4023 / R 0.6481 / AP50 0.4670（35/52/19，**逐位复现 V2.3**）。
    unified@val_3cls racket AP50 0.8192 > racket_v1 0.7580。
  - C++：`c_actual_tests.exe` **46/46 PASS**（含统一模型与类别数守卫）；`pytest tests -q` 94 passed；
    `tools/check_repo.py` 266 files / 0 problems。
  - Python↔C++：8 帧，hand/racket 框数全一致，最大坐标差 **0.0004 px**。
  - ZIP：`C_PERCEPTION_CAPTAIN_INTEGRATION_V2_4.zip`，116,250,413 B，
    SHA256 `7edf80ed…56c4`；解压到 `C:\cap_v24final` 后 `run_demo.ps1` 与 `run_demo.ps1 -Unified`
    均 **exit 0**，包内测试 **46/46 PASS**；V2_1/V2_2/V2_3 哈希未变。
- 未执行检查、阻塞与所需硬件：
  - 阻塞①：**真实目标域没有 racket 真值**。同一段 BNDSTT 域片段，统一模型 racket 最高分 0.003、
    专用 640 模型 0.806，**无法判定谁对**。需要真实域 racket 标注（30–50 框即可起步）。
  - 阻塞②：**训练 val 没有 hand 真值**（ball 233 / racket 550 / hand 0），训练侧无法自检 hand。
  - 未做：RKNN 转换、NPU 实测、上板（BOARD VERIFIED = NO）、真实相机采集。
  - 没有 CUDA：所有训练与推理都是 CPU。
- 修改文件与设计理由：
  - `include/c_perception_engine.hpp`：新增可选 `ModelPaths::unified`、`PerceptionResult::unified_model`、
    `usingUnifiedDetector()`；默认空 → 源码与行为向后兼容。
  - `src/perception_engine.cpp`：统一模型加载（含 3 类校验 `UNIFIED_MODEL_CLASS_MISMATCH`）、
    单次前向按类分发、**丢弃 ball 类**（冻结契约里 ball 只有一个来源 BallTrack）。
  - `src/yolo_detector_onnx.cpp` + `src/internal_onnx.hpp`：从输出形状解析类别数，用于上面的校验。
  - `app/c_perception_cli.cpp`：`--unified-model`、模式打印、`model_versions.unified`；
    顺带修复非 ASCII 图片路径（宽路径 + 字节解码）。
  - `src/detector_backend_c_actual.cpp`：`CActualConfig::unified_model`、新 `mode()` 字符串。
  - `tests/test_c_actual.cpp`：统一模型 8 项断言 + 错误图拒绝 2 项；端到端测试按交付文件名解析。
  - `config/inference.yaml`、`INTERFACE_CONTRACT.md`（第 9 节含兼容性影响表）、`README_CAPTAIN.md`、
    `run_demo.ps1`（`-Unified` 开关，默认分离模型）：文档与入口同步。
  - 设计理由：**统一模型目前 hand recall 更低、racket 在真实域存疑**，所以做成可选路径而不是默认，
    避免静默回退 A/B 已经验收过的能力。
- 下一步及验收条件：
  1. 补 val 的 hand 真值（建集时给 BodyHands/伪标签留 ~10%）→ 训练日志能自检 hand。
  2. 统一模型 hand 配比从 700 提到 4000–6000 张 BodyHands，重训 60 轮（CPU ≈10.6 h）。
     **验收**：`bndstt_manual` R ≥ 0.6481 且 P ≥ 0.40，AP50 不低于 hand_v3。
  3. 补真实域 racket 标注 → 裁决 3.5 节分歧；在此之前 racket 继续用专用模型。
  4. 追平后把 `run_demo.ps1` 默认改为 `-Unified`，再做 RKNN INT8（前 4 通道像素坐标不要量化）。
  5. A/B 复核 `mode()` 新字符串与 `ModelPaths.unified` 字段，确认无字符串精确比较。
