# 任务交接

- 任务编号/负责人：A-USB-FPGA-20261005；蒲公英；本轮由 Codex 实现，无其他 agent 委派。
- 基准提交号/工作分支：基准 `d6cf530`；`codex/a-usb-fpga-pipeline-20261005`。本轮代码提交号以该分支 `git log -1` 为准；没有推送或创建/合并 GitHub PR。
- 当前目标与范围：完成无实物条件下 A 的完整软件、整数参考、前三级 RTL、通信模拟、GUI、验证和部署准备。B/C 的实际模块、后四级 RTL及整机是独立依赖。
- 允许修改的文件：`software/pc_pipeline/`、`tools/a_pipeline/`、`fpga/rtl/a_motion/`、`fpga/sim/a_motion/`、`fpga/projects/a_motion_td/`、本轮报告/清单/交接及现行入口索引。原规划、Word、归档、B/C 正式源码未改写。
- 输入输出/接口版本：`schema_version=1`；共用头文件 `pipeline/pipeline.hpp`；算法 `a-int-v1`；软件 `a-motion-v1-draft-lsb0`。实际硬件协议等待 SDK、技术复核和蒲公英批准。新增 B/C/DMA 库、坐标/时间和兼容性影响见 [草案](../software/pc_pipeline/contracts/a-motion-v1.md)。
- 环境：Windows MSVC、OpenCV 4.13.0、Qt 6.8.3；Ubuntu-24.04 GCC、同版本 OpenCV/Qt；Icarus 12.0；TD 2026.1 SP2.200.067、PH1A90SEG324。精确工具和二进制哈希在 [机器报告](../reports/A职责交付_20261005.json)。

## 直接使用

Windows 双击 `C:\FPGA competition\dist\A-USB-Stereo-Pipeline-1.0.0-Windows\启动回放界面.cmd`。真实素材从“导入截图包”选择原始父目录；人工样例在包内 `fixtures/manifest.json`。导出使用新的目录，已有运行不会覆盖。

构建与独立核对：

```powershell
pwsh -NoProfile -File tools/a_pipeline/build_windows.ps1
build/a_pipeline_windows/pipeline_cli.exe --input data/manifests/a-usb-125-20261005.json --output output/acceptance-new --motion cpu
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/verify_pixels.py --manifest data/manifests/a-usb-125-20261005.json --run output/acceptance-new --output output/acceptance-check.json
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/verify_rtl.py --manifest data/manifests/a-usb-125-20261005.json --output output/rtl-new
pwsh -NoProfile -File tools/a_pipeline/build_td.ps1
wsl -d Ubuntu-24.04 -- bash '/mnt/c/FPGA competition/tools/a_pipeline/build_linux.sh'
```

完整环境、模块接入、部署和负例命令在 [软件说明](../software/pc_pipeline/README.md)。输入清单引用蒲公英本机素材绝对路径，其他机器需重新导入或映射路径并保持哈希。

## 已执行检查及真实结果

[交付报告](../reports/A职责交付_20261005.md)汇总 Windows/Linux 构建、独立 125 对像素、250 眼帧 RTL、随机存储停顿与异常、10000 对生命周期、GUI/CLI 一致、便携运行、Linux V4L2 系统调用、B/C 测试接入、依赖门禁和 ASan/UBSan 结果。原始命令/结果、性能/队列/RSS、源码与工具哈希在机器报告和包内 evidence。

最终前三阶段 RTL逐像素一致；TD gate 综合成功，1227 Slice（1.91%），当前行缓存使用分布式 RAM，具体警告保留。未指定引脚，未执行 place/route。软件输出首帧零 Mask 并标参考无效，坏帧保留旧参考，超时/复位清空参考；晚到语义和替换记录保留来源帧。

## 未执行项与接手入口

B 接手 `MeasurementModule`、同帧 ROI、Mask 与参考时间；接入真实标定/球心/三维/事件，并实现后四级 RTL 和打包。C 接手 `DetectorBackend`，输入原眼 GRAY8，输出原眼 ball/hand/racket 框；按模型版本独立验证实际推理、预处理和截止时间。接口测试库仅用于联调，model/full 会拒绝测试版本。

设备接手 `DmaTransport` 和 `DmaBinding`：提供实际 DMA 驱动、完成描述符、DDR3L IP、引脚及复位/排空策略。`PcieMotionBackend` 已处理容量、身份、过期代际、超时与错误复位，但当前未接实物。AArch64 设置厂商 `AFH03_SYSROOT` 和同架构 OpenCV 后构建，当前门禁确认缺少该依赖。

后续验收按 USB 实际采集、DDR3L、PCIe、B/C 实际模块、独立真实双目评分及整机逐层执行。PC 回放、接口测试、RTL 仿真和综合分别留证，不能据此记为上板或实际模型通过。

## 设计与保留项

共用 C++ 核心避免 CLI、GUI 和模拟通信产生不同算法；异步上下文复制原眼图与身份；环形槽位以受控所有权保持有效。软件草案显式序列化且附黄金向量，实际 SDK 编码由独立绑定提供。TD 使用综合封装控制 IO 数量，板级工程另行绑定。

原文件与归档按原始字节保留，本轮生成工程和素材结果位于 `build/`、`output/`、`dist/`。新的接手者先读 AGENTS.md 与现行规划，不依赖聊天隐含状态。
