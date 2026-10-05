# AFH03 图像处理内核验证记录

验证日期：2026-09-24。工作分支：`codex/afh03-image-pipeline-20260924`，基准提交：`8f94786`。本次结果覆盖 RTL 功能仿真和 PH1A90SEG324 的 TD 综合；没有上板验证。

## 实现范围

新增两路独立 GRAY8 图像处理内核，包括原始灰度保留、可旁路 3×3 去噪、饱和亮度增益/偏置、ROI 裁剪、帧号/时间戳/配置标签传递、输出反压、帧边界原子切换配置，以及输入 SOF/EOL 检查。另提供可选 RGB888 转灰度模块。

接口说明位于 `fpga/afh03_image/INTERFACE.md`，版本为内部草案 `afh03-image-v0.1`。摄像头驱动、Bayer 解码、跨时钟 FIFO、DDR、PCIe、RK3576J 程序和模型均不在本次实现范围内。

## 真实执行的验证

本机执行时使用的 Python：`C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。以下命令均在 `C:\FPGA competition` 执行。

```powershell
& 'C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/run_image_pipeline_tests.py --waves
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_afh03_image.ps1
& 'C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
& 'C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/check_repo.py
```

最终功能仿真目录：`tmp/afh03-image-tests-20260924-225948-699516`。使用 Icarus Verilog `12.0 (devel) (s20150603-1539-g2693dd32b)`，不将其记作正式稳定版 12.0。

每组种子验证 59 个完整帧，3 组随机种子为 1、2476、314159。每组严格匹配 63,477 个整帧输出和 62,904 个 ROI 输出，共计 379,143 个输出传输逐拍匹配。比较内容包括像素、x/y、SOF/EOL/EOF、帧号、64 位时间戳和配置标签。另有 4,096 个 RGB888 转灰度输入，以及 327,680 个亮度组合，全部通过。

图像参考用 Python 对二维图像直接进行九点卷积与边界扩展，不复用 RTL 的行 RAM、窗口寄存器或补边状态机。覆盖常数、斜坡、单点、棋盘和随机图像；1×1、单行、单列、奇数尺寸、2048×3 和 3×2048；ROI 原始/处理后选择、关闭、零尺寸、图外起点、越界截断与 16 位加法边界；亮度饱和；连续有效输入与随机空拍；两支输出各自停顿时保持数据；两路相位不同；帧中提交及随后修改影子配置；一路阻塞时另一路完成；在途复位；非法尺寸、未知地址与错误 SOF/EOL。

原有仓库卫生测试 5 项通过，57 个原有跟踪文件检查为 0 问题。另对本次新增的 18 个文件执行同一 `inspect_file` 检查，结果为 0 问题；仿真、TD 副本和仓库 RTL 的 SHA-256 一致。`git diff --check` 通过。

## TD 工程与资源结果

TD 版本：`Release_2026.1_SP2`，Build `6.2.2.200067`。目标器件：`PH1A90SEG324`，由 TD 选取默认速度等级 `-2`。

最终成功工程：`build/afh03-image-20260924-225924-af6b692b/afh03_image.al`。综合入口 `afh03_image_compile_top` 完整实例化 `afh03_stereo_preproc`；其串行装载和折叠观察接口仅用于收拢内部宽总线，避免把 909 位模块接口直接当成封装引脚。真实板级工程应实例化内核，而不是把这个综合封装连接到摄像头。

另使用 TD 实际执行 `open_project ./afh03_image.al` 和 `close_project` 重新打开工程，日志确认 `Successfully analyzed 6 source files` 和 `AFH03_PROJECT_REOPEN_PASS`，证据为该构建目录的 `verify_open.tcl`、`reopen.log`。这验证了原生项目可由 TD 解析，不代表已操作 GUI 或上板。

最终 `core_gate.area` 报告：包含综合封装共 2,389 LUT、3,282 寄存器、1,996 slice、6 个 ERAM20K、2 个 DSP；分布式 RAM LUT 为 0。slice 统计约为器件资源的 3.10%，ERAM 为 2.21%。纯内核层级报告为 3,038 个时序单元、6 个 ERAM、2 个 DSP；请勿将含封装统计直接当作最终系统资源。

最初的行缓存推断使用分布式 RAM。依据本地 TD《SWUG106 HDL Coding Synthesis User Guide》4.3.14 的 `ram_style="bram"` 规则，并将 RAM 地址宽度约束为实际存储深度后，最终映射为每路 3 个 ERAM20K。此次修改后的 RTL 已重新运行上述完整功能仿真。综合报告未出现锁存器推断；最终运行没有 RAM 回退警告。

TD 综合保留了未分配 96 个封装 IO 的警告，因为本工程没有板级 ADC 管脚约束。这是综合封装的限制，本次没有运行布局布线和 bitgen，也没有打开忽略未约束 IO 的选项。10 ns SDC 只是设计目标，尚不能证明 100 MHz 可收敛。

`reports/afh03-image-20260924-summary.json` 保留仿真摘要、源文件 SHA-256 和本次 TD 证据定位；`reports/afh03-image-20260924-gate.area.txt` 保存综合面积报告。完整仿真输出、波形及 TD 数据库保留在被 Git 忽略的 `tmp/`、`build/`。

## 工具来源与复现限制

本机便携 Icarus 工具来自 Windows 构建发布页 [Icarus Verilog for Windows](https://bleyer.org/icarus/)，包名 `iverilog-v12-20220611-x64_setup.exe`，SHA-256 为 `A614057374DFAED5DA0FE454CDEB410E54981FD85DBD28BD472F4CCB765DEB84`。使用 [innoextract](https://constexpr.org/innoextract/) 的 `innoextract-1.9-windows.zip` 解包到项目 `.tools/`，该 zip 的 SHA-256 为 `6989342C9B026A00A72A38F23B62A8E6A22CC5DE69805CF47D68AC2FEC993065`。没有运行安装程序，也未修改系统 PATH；工具包不进入版本管理。

目前没有执行综合后网表功能仿真、布局布线时序分析、真实摄像头输入、DDR/PCIe 吞吐、CPU/NPU 任务、长时稳定性和双路软件时间校准。接硬件后，须先用已知测试图验证字节序、灰度格式、像素数量、时间戳定义和故障帧作废，再扩大到实时链路。仿真结果不等于这些项目已经通过。
