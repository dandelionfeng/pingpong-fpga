## 目的与关联任务

修复第三部分 PR 在干净 checkout 中无法构建和运行的问题，依据 AFH03 USB 同步双目技术路线、B 最新职责说明及 PR #14 审查意见。本轮重点是恢复正式构建入口、校验第二部分依赖路径，并让 v2 验证脚本不依赖作者本地残留的构建目录。

本轮不是完整第三部分或整机完成声明；不含 A 系统联调、C 实际 YOLO/RKNN 模型、真实相机标定、Linux/ARM、FPGA 综合和上板验证。

负责人：B / cluepiggie。建议分支：`codex/b-trajectory-events-v2`。本 PR 依赖修复后的第二部分 PR；第二部分路径必须为 `software/pc_pipeline/ball_measurement/`，合并顺序和实际基准提交以 GitHub 记录为准。

## 改动范围

- `software/pc_pipeline/trajectory/CMakeLists.txt`：显式检查同级第二部分 `ball_measurement` 依赖并给出路径错误提示。
- `software/pc_pipeline/trajectory/build_and_test.bat`、`build_and_test.ps1`：作为正式可提交的 Windows CMake/Ninja 构建和 8 项 CTest 入口。
- `software/pc_pipeline/trajectory/run_validation_v2.ps1`：支持显式构建目录和 Visual Studio 路径，先调用 builder，再检查生成的 `trajectory_cli.exe` 后运行完整 v2 链路。
- `software/pc_pipeline/trajectory/README.md`：说明干净 checkout、第二部分同级路径、脚本入口和不可上传的 build 目录。
- `reports/第三部分_构建入口与依赖路径修复验证_2026-10-06.md`：本轮实际命令、工具版本、结果和限制。
- `handoffs/2026-10-06-b-trajectory-v2.md`：更新依赖路径、复现入口和交接要求。

三维轨迹、事件算法和第二部分源码未在本轮改写；本 PR 不再通过本地临时复制目录证明可构建。

## 接口或行为影响

- CMake 要求 `software/pc_pipeline/ball_measurement/` 与 `software/pc_pipeline/trajectory/` 同级；缺少该目录时配置明确失败。
- `run_validation_v2.ps1` 新增可选参数 `-BuildDirectory`、`-VisualStudioPath`，默认仍使用 `trajectory/build-ninja-release` 和自动发现的 Visual Studio。
- v2 脚本每次先调用 `build_and_test.bat`，成功后检查同一构建目录中的 `trajectory_cli.exe`，再进行校准、图像、事件和证据步骤。
- `build-ninja-release/`、exe、dll、lib、obj、日志和生成输入仍属于本地产物，不上传到 GitHub。
- 该 PR 仍使用 `b-trajectory-v2-draft` 和 `b-calibration-v1-draft`，共同 PCIe 字节布局、模型协议和判罚阈值未冻结。

## 验证证据

- 实际执行的命令/工具版本：

  ```powershell
  & '.\\software\\pc_pipeline\\trajectory\\run_validation_v2.ps1' `
    -OutputDirectory '_deliveries\\part3_v2_repair_validation' `
    -BuildDirectory 'software\\pc_pipeline\\trajectory\\build-ninja-release'
  ```

  MSVC 19.43.34808.0、Windows SDK 10.0.22621.0、CMake 3.30.5-msvc23、Ninja 1.12.1、OpenCV C++ 4.10.0；Python 3.12.14、NumPy 1.26.4、opencv-python 4.10.0.84、matplotlib 3.9.2。

- 实际结果与报告路径：

  - 8/8 CTest 通过（第三部分 62 项检查、第二部分 42 项回归）；
  - 84/84 文件场景通过；
  - 原棋盘留出 4/4、扩展棋盘留出 6/6 通过；
  - 校正预览、88 个事件窗口证据和 12 张图表生成完成；
  - 入口输出 `PART3_V2_VALIDATION_PASS`。

  报告：`reports/第三部分_构建入口与依赖路径修复验证_2026-10-06.md`。本地完整日志：`_deliveries/part3_v2_repair_validation/`。

  该回归使用 B 生成的合成双目图像、合成 Mask 和 synthetic replay，不能作为真实相机、YOLO/RKNN、FPGA 或上板证据。

- 尚未执行的仿真/综合/上板验证及原因：

  尚未执行 A 系统联调、C 实际模型和独立评分、真实 OV9281 标定/同步/米制精度、Linux/ARM、目标板性能、FPGA 综合和上板。正式仓库检查与 `repository-checks` 结果应在第二部分路径修复合入并从干净 checkout 创建/更新 PR 后重新确认。

## 交接

- [x] 已检查本次增量内容，不含密钥、模型权重、视频、二进制、build 目录或生成工程；网页提交后仍需核对 PR Files changed。
- [x] 已更新构建入口、依赖路径、运行参数和受影响说明；`build_and_test.bat`/`.ps1` 已列为必须提交的源码入口。
- [x] 需要另一模块配合时，已明确负责人和步骤：先合并修复后的第二部分 PR，使 `software/pc_pipeline/ball_measurement/` 与本目录同级，再从干净 checkout 运行 v2；A 提供同帧输入，C 提供实际模型/独立评价，具体入口见 `handoffs/2026-10-06-b-trajectory-v2.md`。

最终审批与合并由 FengFengKang 确认。本正文不代表已经获得批准；依赖修复、检查通过且获确认后使用 Squash and merge。
