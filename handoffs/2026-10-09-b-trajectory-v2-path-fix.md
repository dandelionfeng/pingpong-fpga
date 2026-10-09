# B 第三部分路径修正版交接

- 负责人：B / cluepiggie。
- 目标：修复第三部分 PR 在干净 checkout 中找不到第二部分依赖、构建入口不完整和旧 `BPart2/` 副本混入的问题。
- 允许修改：`software/pc_pipeline/trajectory/`、`tools/fixtures/trajectory*`、`reports/trajectory_v2/2026-10-09/`、本交接文件及第三部分现行报告。第一部分、第二部分算法、A/C 源码不改。
- 依赖：主仓库最新 `main` 已合入第二部分后，路径必须是 `software/pc_pipeline/ball_measurement/`，与 `software/pc_pipeline/trajectory/` 同级。第三部分源码包不重复提交第二部分源码，也不保留 `BPart2/`。
- 构建入口：从仓库根运行 `software/pc_pipeline/trajectory/run_validation_v2.ps1`；可传 `-OutputDirectory`、`-Python`、`-OpenCVDir`、`-BuildDirectory`、`-VisualStudioPath`。脚本会检查第二部分路径、调用 `build_and_test.bat`、运行同一构建目录的 CLI 和完整 v2 链路。
- 实际验证：MSVC 19.43.34808.0、Windows SDK 10.0.22621.0、CMake 3.30.5-msvc23、Ninja 1.12.1、OpenCV C++ 4.10.0、Python 3.12.14、NumPy 1.26.4、opencv-python 4.10.0.84、matplotlib 3.9.2；输出 `PART3_V2_VALIDATION_PASS`。
- 结果：62 项第三部分 C++ 检查、42 项第二部分回归、8/8 CTest、84/84 文件场景、棋盘留出 4/4 与 6/6、88 个事件证据窗口、12 张图表。
- 未验证：根仓库 `check_repo.py --staged` 与 unittest、A 系统联调、C 真实 YOLO/RKNN 及独立评分、真实 OV9281 标定/同步/米制精度、Linux/ARM、FPGA 综合和上板。
- 接手步骤：先确认第二部分已在主仓库同级路径；把本模块源码和第三部分工具/报告/交接加入 `codex/b-trajectory-events`；从干净 checkout 重跑 v2；检查 Files changed 中没有 `BPart2/`、二进制、权重或根清单覆盖。
