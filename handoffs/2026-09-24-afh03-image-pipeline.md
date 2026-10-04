# 任务交接

- 任务编号/负责人：AFH03-IMAGE-001 / Codex；由蒲公英提出，将 AFH03 技术路线中不依赖前序硬件的图像处理先写入 TD 工程。
- 基准提交号/工作分支：`8f94786` / `codex/afh03-image-pipeline-20260924`。未自动提交、推送或改动现有 Word、采购文档及既有规划接口。
- 当前目标与不包含的范围：完成双路 GRAY8 处理、ROI、帧元数据、配置及反压，并进行功能仿真和 TD 综合。不包含摄像头/CDC/DDR/PCIe 适配、NPU 模型、双目同步、软件校准、板级管脚及 bitstream。
- 允许修改的文件：`fpga/rtl/afh03_image/`、`fpga/sim/afh03_image/`、`fpga/afh03_image/`、`tools/run_image_pipeline_tests.py`、`tools/build_afh03_image.ps1`、本次验证报告/摘要/面积报告和本交接。其他已有工作保持原状。
- 输入输出/依赖的接口版本：新增内部草案 `afh03-image-v0.1`，详见 `fpga/afh03_image/INTERFACE.md`。输入双路独立 GRAY8 和 SOF/EOL/帧号/时间戳；输出整帧原始+处理灰度、可选 ROI，以及坐标和配置标签。没有变更旧 v1.3 或冻结 RK3576J 通信报文。
- 环境与复现命令：Windows PowerShell；TD `Release_2026.1_SP2` / Build `6.2.2.200067`；Icarus `12.0 (devel) (s20150603-1539-g2693dd32b)`；Python 仅依赖标准库。运行 `python tools/run_image_pipeline_tests.py --waves` 和 `powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_afh03_image.ps1`。本机实际 Python 路径、工具来源和完整命令见 `reports/AFH03图像处理验证.md`。
- 已执行检查及真实结果：3 个随机停顿种子，每种 59 帧，共 379,143 次输出传输逐拍匹配；RGB 4,096 项、亮度 327,680 项通过。TD 原生工程创建、重新打开及 PH1A90SEG324 综合通过；最终包含封装 2,389 LUT、3,282 寄存器、6 ERAM20K、2 DSP，分布式 RAM 为 0。原有 5 项卫生测试、57 个跟踪文件检查和本次新增 18 个文件检查通过；仿真/综合/仓库 RTL 哈希一致。详细计数保存在摘要 JSON。
- 未执行检查、阻塞与所需硬件：没有网表仿真、布局布线或上板。硬件确定后需要实际摄像头数据格式/时钟/接口、板卡原理图与引脚表、DDR 和 PCIe 官方例程及 RK3576J SDK。当前缺失不会阻止独立内核仿真，但不能据此声称整机帧率、延迟或判罚精度达标。
- 修改文件与设计理由：将摄像头协议和系统通信放在内核之外，保留 GRAY8 握手入口及完整帧元数据；同时保留原始灰度与可选处理结果；以原子帧边界配置避免同帧混用参数；三行缓存使用 ERAM 减少 LUT 消耗。`afh03_image_compile_top` 仅为 TD 综合封装，实际板级工程使用 `afh03_stereo_preproc`。
- 下一步及验收条件：接手人先读 `fpga/afh03_image/README.md` 和接口草案，用已知图案跑通单路适配→内核→缓存，确认无丢帧、帧号/时间戳/配置标签正确、故障帧不会提交，再接双路与 PCIe/CPU。摄像头不能被 ready 停顿，入口必须提供跨时钟 FIFO、溢出检测和整帧丢弃恢复。外部协议、模型输入和坐标变换冻结前由相关负责人评审。

最终功能仿真：`tmp/afh03-image-tests-20260924-225948-699516/summary.json`。

最终 TD 工程：`build/afh03-image-20260924-225924-af6b692b/afh03_image.al`。打开该原生项目即可查看源码和综合层级；每次修改仓库源码后应重新执行构建脚本，生成目录是对应版本的副本。

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖上一段聊天隐含的信息。继续遵守未经蒲公英要求不自动启动其他 agent 的规则。
