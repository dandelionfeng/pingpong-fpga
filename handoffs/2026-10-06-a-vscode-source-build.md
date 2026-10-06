# 任务交接

- 任务编号/负责人：A-VSCODE-SOURCE-BUILD-20261006；蒲公英；Codex。
- 基准提交号/工作分支：`3be59aa`；`codex/a-usb-fpga-pipeline-20261005`；本次为 A 交付的构建入口修复，未推送。
- 当前目标与范围：修复解压源码在 VS Code 中找不到 OpenCV/Qt 的问题，补齐 IDE 构建的运行库部署；算法和 B/C 公共接口保持原实现。
- 允许修改的文件：A 的 CMake、Windows 构建脚本、源码工作区、说明与本次交接/验证记录；本机解压目录的相关配置。
- 输入输出/依赖的接口版本：仍采用原软件接口。仓库与修正版 ZIP 保留 OpenCV 4.13.0、Qt 6.8.3 版本要求；解压目录中用户已有的放宽 OpenCV 版本修改保留。
- 环境与复现命令：Windows、MSVC 2022、OpenCV 4.13.0、Qt 6.8.3。先打开 `software/pc_pipeline/AUsbStereoPipeline-Windows.code-workspace`，选择配置预设 `Windows x64 / MSVC 2022`、生成预设 `windows-debug`；详细说明见软件 README。

在 `software/pc_pipeline` 目录中运行：

```powershell
cmake --preset windows-msvc
cmake --build --preset windows-debug
ctest --preset windows-debug
```

原脚本入口在解压或仓库根目录运行：

```powershell
pwsh -NoProfile -File tools/a_pipeline/build_windows.ps1
```

- 已执行检查及真实结果：原解压目录 CMake 配置、Visual Studio Debug 构建和核心测试通过；新预设配置、Debug 构建和核心测试通过；仓库 Ninja Release 构建和核心测试通过；CLI 处理 8 对固定样例、错误数 0，Mask 序列哈希与原便携程序一致。VS Code 扩展成功读取、验证和展开预设；配置/生成的执行结果另由 CMake 命令行日志记录。具体记录见 `reports/a-vscode-source-build-20261006.json`。
- 未执行检查、阻塞与所需硬件：本次没有重跑完整 GUI 交互、125 对 RTL、10000 对压力或 Linux/实物验收。隐藏窗口启动检查无法获得可靠窗口标题，记录为 inconclusive，未记作 GUI 验收通过。原始验收报告仍按 2026-10-05 的原版本阅读。
- 修改文件与设计理由：`cmake/LocalDependencies.cmake` 在 Windows 下为当前目录及祖先目录的 `.tools` 添加依赖查找提示，保留显式路径优先级；`CMakePresets.json` 绑定 Windows x64 生成器；工作区绑定源目录和代码提示；CMake 在构建后部署所选配置的 OpenCV DLL 和 Qt 文件；脚本复用同一配置与部署逻辑。
- 下一步及验收条件：本机无需重新下载 OpenCV/Qt。其他机器在解压根目录运行 `setup_windows.ps1`；依赖位于另一仓库时设置 `PIPELINE_DEPENDENCIES_ROOT`，或指定 `OpenCV_DIR`/`Qt6_DIR`。使用修正版源码 ZIP 交接；原 ZIP、便携包及原算法验收材料保留。

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖聊天隐含状态。
