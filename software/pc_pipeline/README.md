# A USB 双目处理工程

这是 A 职责的完整本地实现：输入、缓存、七级整数运动前端、异步检测调度、通信模拟、B/C 接口、Qt 回放、CLI 导出及设备适配边界。真实模型、测量算法和 FPGA 后四级由 B/C 提供；缺少模块时输出 `unavailable`，`--full` 会明确拒绝。

验收记录见 [A 交付报告](../../reports/A职责交付_20261005.md)，接手入口见 [交接](../../handoffs/2026-10-05-a-usb-fpga-pipeline.md)。软件契约见 [接口草案](contracts/a-motion-v1.md)。

## Windows 使用

VS Code 开发入口为本目录的 `AUsbStereoPipeline-Windows.code-workspace`，双击后选择“在 VS Code 中打开”。工作区指定 CMake 源目录、代码提示提供者，并启用 `CMakePresets.json`。选择配置预设 `Windows x64 / MSVC 2022` 和生成预设 `windows-debug` 或 `windows-release`，在 CMake 面板执行配置、生成，再选择 `pipeline_gui` 或 `pipeline_cli` 启动。普通文件夹打开时，仓库根目录的 CMake 源目录应设置为 `${workspaceFolder}/software/pc_pipeline`。

源码包省略 OpenCV/Qt 开发库；便携包内 DLL 用于运行程序。CMake 自动查找当前目录及父目录下由 `setup_windows.ps1` 安装的 `.tools/opencv413` 和 `.tools/qt`，因此本机 `dist/` 中解压的源码可以复用主仓库依赖。换电脑时先在解压根目录运行 `tools/a_pipeline/setup_windows.ps1`。依赖装在其他目录时，配置 `-DPIPELINE_DEPENDENCIES_ROOT=含.tools的目录`，或指定 `OpenCV_DIR` 和 `Qt6_DIR`。脚本构建可使用 `build_windows.ps1 -DependenciesRoot '依赖所在目录'`。默认固定 OpenCV 4.13.0 与 Qt 6.8.3；移除版本号无法解决找不到开发库的问题。

IDE 生成会把所选 Debug/Release 的 OpenCV DLL 复制到输出目录，并为 GUI 部署 Qt 运行文件。Windows 便携包与 IDE 的构建目录各自保留。

当前便携包为 `dist/A-USB-Stereo-Pipeline-1.0.1-Windows/`，下载见 [1.0.1 Release](https://github.com/fengfengkang/pingpong-fpga/releases/tag/a-pipeline-pc-20261012)。双击 `启动回放界面.cmd`；使用“导入截图包”选择包含 `export.json`、`pairs.csv` 的父目录。也可打开 GRAY8/YUY2/MJPG 输入清单。先播放或拖动进度条，再选择原图、搜索图或七级阶段，点击左/右画面检查同帧 256×256 ROI。`fixtures-mjpeg/manifest.json` 和 `检查MJPEG样例.cmd` 提供独立人工 JPEG 样例；原人工样例仍在 `fixtures/`。

预览使用 CPU 共用核心；“运行并导出全序列”按所选 CPU/模拟 DMA 后端运行。检测框回放的框属于指定 `source_pair_id`，异步迟到结果归档到用户 AppLocalDataLocation 下 `AUsbStereoPipeline/preview/`，只有与当前画面帧号、采样时间相符的框才叠加。实际 C 模型依赖可选库，界面会报告缺少的模块。

CLI 从仓库根目录运行：

```powershell
pwsh -NoProfile -File tools/a_pipeline/setup_windows.ps1
pwsh -NoProfile -File tools/a_pipeline/build_windows.ps1
build/a_pipeline_windows/pipeline_cli.exe --import-export '截图包父目录' --manifest 'output/input.json'
build/a_pipeline_windows/pipeline_cli.exe --input 'output/input.json' --output 'output/run-new' --config software/pc_pipeline/configs/default.json
build/a_pipeline_windows/pipeline_cli.exe --input 'output/input.json' --output 'output/mock-new' --motion mock-dma --no-images
build/a_pipeline_windows/pipeline_gui.exe --input 'output/input.json'
```

输出目录需为新目录，程序保留已有结果。`--no-images` 只导出 JSONL/CSV；默认保存原图、搜索图、七级图、Mask、LSB0 二进制和中心检查 ROI。中心 ROI 明确标为 `image_center_not_ball_measurement`。点击选择的 ROI 随 GUI 当前帧导出，并保存原点、有效区域和补齐值。

`--realtime --mock-delay-ms 80` 可验证慢处理与替换记录；批处理以背压保留全部有效输入。`--detector replay --replay FILE.json` 接入框回放，`--detect-right` 或 B 的 `requestRightDetection()` 请求右眼检测。左右共享预算，先提交左眼；右眼请求等待共享预算余量。`--detector model --full` 要求实际 B/C 模块。`--motion pcie` 要求厂商传输库，不会自动切换到软件结果。

## Ubuntu 24.04

本机已配置 WSL Ubuntu-24.04。依赖安装脚本第一步以 root 运行；后续以 `dandelion` 用户运行。OpenCV 来源为已校验的 Windows 官方包内源码，复制到 Linux ext4 编译，固定 4.13.0；Qt 固定 6.8.3，包含其 ICU 73 运行库。

```powershell
wsl -d Ubuntu-24.04 -u root -- bash '/mnt/c/FPGA competition/tools/a_pipeline/setup_linux.sh'
wsl -d Ubuntu-24.04 -- bash '/mnt/c/FPGA competition/tools/a_pipeline/build_linux_dependencies.sh'
wsl -d Ubuntu-24.04 -- bash '/mnt/c/FPGA competition/tools/a_pipeline/setup_linux_qt.sh'
wsl -d Ubuntu-24.04 -- bash '/mnt/c/FPGA competition/tools/a_pipeline/build_linux.sh'
```

Linux 默认依赖/构建根在 `$HOME/.local/share/afh03-a-pipeline/`。`A_PIPELINE_DEPS`、`A_PIPELINE_BUILD` 可指定构建位置。跨平台清单保持原内容哈希，只映射本地路径：

```powershell
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/manifest_paths.py --input output/input.json --output output/input-linux.json
wsl -d Ubuntu-24.04 -- bash -lc '$HOME/.local/share/afh03-a-pipeline/pipeline-build/pipeline_cli --input "/mnt/c/FPGA competition/output/input-linux.json" --output "/mnt/c/FPGA competition/output/linux-new" --no-images'
```

## B/C 接入

1.0.1 只增加输入解码边界：B/C 接收的原眼 GRAY8、搜索图、Mask、ROI 与身份字段保持原样，配置、算法阈值、模型预处理、FPGA 协议和界面设置未变。JPEG 是有损格式，解码后的像素不能作为相机未压缩 Y 的逐像素真值；真实测量精度需另行验证。

各模块用 `pipeline_module_api` 获取头文件、OpenCV 和 JSON 依赖，提供 `pipeline_b_module` / `pipeline_c_module` 库和 `pipeline::register_b_module(Registry&)` / `register_c_module(Registry&)`。通过 `-DPIPELINE_B_MODULE_DIR=绝对目录`、`-DPIPELINE_C_MODULE_DIR=绝对目录` 配置。接口和坐标规则见契约；B 必须把迟到语义归档到来源帧，三维输出用米并区分 observed、predicted、invalid。

`tests/modules/b`、`tests/modules/c` 是接口测试库，返回 `integration-test` 版本与明确无测量的结果，仅在 `--detector module-test` 下使用。它们不会通过 `model` / `--full` 的实际模块门禁。C 的实际后端声明 `actual-model`，提供模型版本，并遵守可中断的停止/超时契约；模型预处理及类别映射由 C 负责。

## 像素、缓存和输出

输入支持 2560×720 YUY2 与左右 1280×720 GRAY8，按行 stride 读数据，版本 1 的 stride 上限 65536。逐字节保留 Y 值，未做亮度范围扩展。2×2 平均采用 `(sum+2)>>2`。搜索点中心映射为 `(2u+0.5, 2v+0.5)`；框边界映射为坐标与宽高乘 2。ROI 原点为 `floor(center)-128`，有效区域裁到原图边界，其余补 0。

### MJPEG 输入（1.0.1）

文件清单沿用 `schema_version: 1`，每条帧的 `format` 可为 `MJPG` 或 `MJPEG`，`width: 2560`、`height: 720`、`file` 指向一张完整 JPEG，`sha256` 为压缩文件的哈希；`stride` 可省略或为 0。其余身份和时间字段沿用原规则。左右各占一半，JPEG 直接解码为 GRAY8，不做 EXIF 旋转、RGB 往返或亮度范围扩展。解码前检查 JPEG 标记、尺寸、完整结尾及 16 MiB 长度上限；坏帧归档并保留旧运动参考。此入口按每帧 JPEG 接收，不读取 AVI 容器或一文件拼接的多帧视频。

截图包在 `export.json` 声明 `pixel_format: "MJPG"`（或 `MJPEG`），`pairs.csv` 的 `pair_file` 指向各 JPEG；可保留 `geometry_status` 和 `time_source`，未提供几何状态时标记 `unverified_stereo`。Windows GUI/CLI 均使用文件入口；实时相机入口仍为 Linux V4L2。

Linux 相机默认依次协商 YUYV 2560×720@60 和 MJPG 2560×720@60。旧相机能够提供 YUYV 60 fps 时保持原格式；不满足时尝试 MJPG，均失败则给出具体原因。可在 V4L2 清单额外设置 `pixel_format: "MJPG"` 或 `"YUYV"` 强制格式。尺寸、60 fps 请求、手动曝光、4 个采集缓冲与 500 ms 等待保持原设定；压缩帧按 `bytesused` 读取，沿用内核采样时间与序号，不以解码完成时间替代。仓库原配置文件未修改。

复现人工输入与测试：

```powershell
python tools/a_pipeline/generate_mjpeg_fixture.py --output output/mjpeg-new --pairs 125
build/a_pipeline_windows/pipeline_cli.exe --input output/mjpeg-new/manifest.json --output output/mjpeg-run
ctest --test-dir build/a_pipeline_windows --output-on-failure
```

生成器依赖 NumPy/Pillow，JPEG 质量 95 仅用于人工样例；不设置相机压缩质量。人工 16 ms 时间戳明确标记 `synthetic_16ms_fixture`，不代表实测 60 fps。验证记录见 [MJPEG 报告](../../reports/MJPEG适配验证_20261012.md)。

发布包可用 `tools/a_pipeline/package_release.py --help` 查看参数：指定当前构建目录、同版本许可证目录、MSVC CRT、原人工样例和 MJPEG 人工样例，输出到全新目录。它只复制 Git 跟踪的源码，避免打包构建目录、设备 SDK 或模型。

Gaussian 是 `[1,2,1]` 外积核，`(sum+8)>>4`；差值严格大于 12 才前景。后四级为腐蚀、膨胀、膨胀、腐蚀，所有阶段复制邻边。首帧 Mask 全零，`reference_valid=false`。软件双眼整对成功才更新前帧；坏帧、注入失败保留旧参考，配置切换/复位/运动超时清空参考。

原图缓存固定 8 对，通过 `shared_ptr<const FramePair>` 保证持有者的图像不被覆盖；异步检测另行复制原眼图与元数据。默认队列为输入 8、检测待处理 2、完成 8、显示 1，检测并发 1、预算 25 次/秒、超时 500 ms。输入/检测/完成/运动队列容量及预算可通过 `configs/default.json` 调整；显示保持最新一帧。输入坏帧记录来源清单、实际长度/哈希等异常证据。

`run.json` 保存版本、模式、配置、输入/回放哈希和实测耗时；`frames.jsonl` 保存两眼参考身份、Mask 哈希及 B 状态；`detections.jsonl` 保存来源帧、眼别、参考身份、任务/代际和结果状态；`errors.jsonl` 保存坏帧、替换及失败。CSV 算法时间是采样时间，完成时间单独记录。独立 truth 从评分器读取，共用核心没有 truth 输入入口。

## RTL 和 TD

源码在 `fpga/rtl/a_motion/`。Gaussian 使用两行同步缓存；外部存储保存每眼活动/暂存银行，整眼事务确认后切换。读、写、输出通道均按 valid/ready 停顿保持，响应带 epoch，读响应在同一 epoch 内须有序。

```powershell
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/verify_rtl.py --output output/rtl-small-new --waves
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/verify_rtl.py --manifest output/input.json --output output/rtl-all-new
pwsh -NoProfile -File tools/a_pipeline/build_td.ps1
```

TD 工程定位在 `build/a-motion-td-latest.txt`。`a_motion_compile_top` 是可观察的寄存器综合封装，保留全部核心逻辑；实际 AFH03 的引脚、PCIe endpoint、DDR3L IP、时序收敛和 bitstream 在 SDK 到位后绑定。10 ns SDC 是请求约束，当前报告为综合资源，未作板端频率验收。TD 当前将行缓存映射为分布式 RAM，其警告保留在原始日志。

## 验证与部署入口

```powershell
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/generate_fixture.py --output output/fixture-new
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/verify_pixels.py --manifest output/input.json --run output/run-new --output output/pixel-check.json
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/verify_runtime.py --executable build/a_pipeline_windows/pipeline_cli.exe --manifest output/input.json --replay output/fixture-new/replay.json --output output/runtime-new
.venv/a_pipeline/Scripts/python.exe tools/a_pipeline/stress_monitor.py --executable build/a_pipeline_windows/pipeline_cli.exe --manifest output/input.json --replay output/fixture-new/replay.json --pairs 10000 --output output/stress-new
```

独立全素材像素检查期望当前 125 对包。固定样例生成器产出带行填充的独立双眼人工图和明确标记的框回放，用于环境与接口核对。CPU/模拟 DMA/GUI 使用同一像素核心；参考核对由 NumPy 直接九点卷积与布尔窗口独立实现。

Linux V4L2 输入见 `configs/v4l2.json`，严格请求 YUYV 2560×720@60、手动曝光、MMAP，并校验驱动返回格式和帧长度。当前验证是模拟系统调用边界，真实 USB 采集待相机。`deploy_linux.sh BUILD STAGE` 生成本地 x64 运行目录、共享库、启动器及依赖检查；它不向设备传送文件。

AArch64 工具链为 `cmake/aarch64-linux.cmake`。设置 `AFH03_SYSROOT` 指向厂商 RK3576J rootfs，准备 AArch64 OpenCV 4.13.0 后配置 `-DCMAKE_TOOLCHAIN_FILE=... -DPIPELINE_BUILD_GUI=OFF`。缺少 sysroot 时配置给出具体错误。厂商 PCIe 接入见 [依赖清单](contracts/hardware-dependencies.json)，须提供 `pipeline_dma_module` 和经技术复核、蒲公英批准的实际编码绑定。

本次素材左右眼为单目复制，16 ms 是视频导出请求间隔。它能验收 A 的像素与生命周期链路，未提供三维精度、真实模型准确率、实际 60 fps USB 采集或上板证据。
