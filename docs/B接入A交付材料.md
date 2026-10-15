# B 接入 A 的交付材料

2026-10-12更新A输入与下载入口；A 1.0.1增加MJPEG，B/C接口保持原样。以下B模块审查状态沿用2026-10-08记录。A软件接口 `a-motion-v1-draft`，旧B PR #12/#13/#14已关闭，修订#16/#17已合入，#18待修改；复核见[本轮报告](../reports/PR审查_20261008.md)。本页提供共用核心、输入、整数参考与接入入口；B 的实际测量、三维、事件与后四级 RTL 仍由其模块完成。本次发布在团队私人仓库中。

## 下载与运行

当前软件发布入口：<https://github.com/fengfengkang/pingpong-fpga/releases/tag/a-pipeline-pc-20261012>。A/B人工输入及旧审查证据仍在[原Release](https://github.com/fengfengkang/pingpong-fpga/releases/tag/a-pipeline-pc-20261006)。

A的PR #15已合入`main`，B球心及形态学参考也已合入。从干净checkout执行`git fetch origin`，基于最新`origin/main`建立自己的适配分支；保留已有B分支与未提交修改。旧A任务分支已在合并后删除，不再作为接手入口。

| 附件 | 用途 | 打开方式 |
| --- | --- | --- |
| `A-USB-Stereo-Pipeline-1.0.1-Windows.zip` | MJPEG兼容 Windows x64 GUI/CLI、运行库、许可证及本轮证据 | 解压后双击 `启动回放界面.cmd`；检查样例用 `检查固定样例.cmd` |
| `A-USB-Stereo-Pipeline-1.0.1-source.zip` | 仓库源码、最新 VS Code/CMake 修复、接口、脚本及交接 | 解压后打开 `software/pc_pipeline/AUsbStereoPipeline-Windows.code-workspace` |
| `A-B-Integration-20261006.zip` | 8 对人工双眼输入、七级图、阈值与 Mask 位流、参考身份和文件哈希 | 解压后读取 `sample-index.json`；`inputs/manifest.json` 可导入 A GUI/CLI |
| `PR-Review-Evidence-20261006.zip` | 本次 PR 的构建、测试、失败复现日志和原始测试程序 | 从包内 `README.md` 开始 |

当前软件 SHA-256、字节数和源码版本见新版 Release 的 `release-manifest-20261012.json` 与 `SHA256SUMS-20261012.txt`。原发布清单保留其历史日期。旧1.0.0软件附件已由1.0.1替代，原人工输入和审查附件保留。便携包包含当前A源码；完整仓库源码另有独立source ZIP。源码附件不含OpenCV/Qt开发库，便携包DLL用于运行。

MJPEG在A输入边界解码，B继续获取同尺寸GRAY8原眼、搜索图与Mask，无需解析JPEG。后续实拍需单独评估压缩对球心质量的影响，算法阈值与标定接口没有随本次适配调整。

新电脑先安装 Visual Studio 2022 的桌面 C++ 工具与 Windows SDK、CMake，以及 Python + NumPy/Pillow。仓库根执行：

```powershell
pwsh -NoProfile -File tools/a_pipeline/setup_windows.ps1
pwsh -NoProfile -File tools/a_pipeline/build_windows.ps1
```

固定 OpenCV C++ 4.13.0、Qt 6.8.3。共享依赖也可通过 `-DependenciesRoot` 或 CMake 的 `PIPELINE_DEPENDENCIES_ROOT` 指向含 `.tools` 的目录。不要通过移除 OpenCV 版本要求来解决开发库路径问题。B 独立模块在本机使用同一 OpenCV 4.13.0 已通过构建和现有检查。

## CPU 测量接入

公共头文件 [pipeline.hpp](../software/pc_pipeline/include/pipeline/pipeline.hpp) 定义 `FramePair`、`MotionResult`、`DetectionResult`、`MeasurementModule` 和 `Registry`。完整规则在 [接口草案](../software/pc_pipeline/contracts/a-motion-v1.md)。

| B 模块数据 | A 来源 | 接入规则 |
| --- | --- | --- |
| `GrayFrame.gray` | `FramePair.original[eye]` | 1280×720 GRAY8，同帧原眼，不改写共用 Mat |
| `MotionFrame.mask` | `MotionResult.eyes[eye].stages[6]` | 640×360，CPU 为 0/255；设备只有 Mask 时保留其可用阶段标记 |
| `FrameStamp.pair_id/sample_time_ns/eye` | `Meta.pair_id/eye_timestamp_ns[eye]` 和眼索引 | 保留采样时间；完成时间另存，不推算 `reference_id=pair_id-1` |
| 配置/标定/模型版本 | `Meta` 中对应字符串 | `unavailable` 是缺失状态，不能替换成虚构的标定或模型版本 |
| 运动参考 | `EyeMotion.reference_valid/reference_id/reference_timestamp_ns` | 首帧参考无效；坏帧不得以零 Mask 伪装成观测 |
| 检测结果 | `process` 的同帧框及 `acceptDetections` 的迟到框 | 按来源帧、眼别、版本归档；在线事件按实际到达顺序接收 |

B 提供 `pipeline_b_module` CMake 库，链接 `pipeline_module_api`，实现 `pipeline::register_b_module(Registry&)` 并设置 `registry.measurement`。真实球心/三维/事件适配层继承 `MeasurementModule`，不可直接把独立 `ball_measurement` 库声明为已接通。最小结构参考 [接口测试库](../software/pc_pipeline/tests/modules/b/module.cpp)；该测试库输出 `invalid_integration_test`，不会提供真实测量。

```powershell
cmake -S software/pc_pipeline -B build/a-with-b -G 'Visual Studio 17 2022' -A x64 '-DPIPELINE_B_MODULE_DIR=C:/work/b-adapter'
cmake --build build/a-with-b --config Release
ctest --test-dir build/a-with-b -C Release --output-on-failure
```

先将 #13 的 `BPart2/` 包装层恢复成文档约定目录，#14 才能找到同级 `ball_measurement/`。若 B 保留其他布局，构建、文档、脚本和下游依赖必须一起更新。

三维单位为米，原始观测、滤波与预测独立输出；预测找到同帧真实像素后才可变成观测。C 的 `ball/hand/racket` 实际模型缺失时，仍按 `unavailable` 或显式回放模式运行。完整系统 `--full` 的 B/C 门禁须在适配后共同验收。

## ROI 与 RTL 对接复核

搜索中心映射为 `2u+0.5`，框边界和宽高乘 2。A 的检查 ROI 原点为 `floor(center)-128`、默认补 0；B 当前测量 ROI 采用 replicate，且排除补齐像素。两者用途和填充方式已有差异，适配层保留 B 的测量规则与有效区域，不能用 A 的中心检查 ROI 替代测量输入。

A 前三级 [motion_front3.v](../fpga/rtl/a_motion/motion_front3.v) 通过 `out_valid/out_ready/out_mask` 输出阈值像素，附 `out_x/out_y/out_last`、眼别、pair/time/config 和参考身份。帧启动为独立 `start_valid/start_ready`；成功完成后的 `commit` 才切换前帧银行，短帧/失败走 `abort_frame`。B 后四级适配必须传递相同身份，并明确启动边沿是否消费首像素。

后四级为 3×3 复制邻边的腐蚀、膨胀、膨胀、腐蚀。低位优先草案的黄金向量是 [mask-golden-v1.json](../software/pc_pipeline/contracts/mask-golden-v1.json)：32 像素得到 `81 02 04 40`。搜索图整眼位流为 28,800 字节。草案尚未作为厂商 DMA 协议冻结；A/B 技术复核后交蒲公英批准实际硬件绑定。

## 样例内容与复现

人工样例两眼不同，含带行填充 YUY2 和成对 GRAY8、中文文件名；8 对按 16 ms 人工时间排列。每眼提供原图、搜索图、七级 PNG、最终 `mask_lsb.bin` 和前三级 `threshold_lsb.bin`。`sample-index.json` 中路径相对包根目录，首帧 `reference_valid=false`。

本次实际运行 CPU 与模拟 DMA，Mask 序列及参考身份一致；NumPy/Pillow 独立核对 176 张图、48,971,776 个像素，全部通过。详情见 [样例验证记录](../reports/a-b-integration-20261006.json)。输入是接口与整数运算样例，没有米制标定或真实模型准确率结论。

从仓库根复现，输出使用新目录：

```powershell
python tools/a_pipeline/generate_fixture.py --output output/b-fixture-new/inputs
& '.\build\a_pipeline_windows\pipeline_cli.exe' --input output/b-fixture-new/inputs/manifest.json --output output/b-fixture-new/cpu --motion cpu
& '.\build\a_pipeline_windows\pipeline_cli.exe' --input output/b-fixture-new/inputs/manifest.json --output output/b-fixture-new/mock --motion mock-dma --no-images
python tools/a_pipeline/package_b_fixture.py --fixture-dir output/b-fixture-new --output dist/b-fixture-new.zip --report output/b-fixture-new/check.json --code-commit <所使用的A提交号>
```

CPU 图用于逐像素参考，B 的评分真值仍由独立评分器读取，不进入 A/B 被测算法。

## 仍需要蒲公英协调的材料

| 材料 | 用途和取得时机 |
| --- | --- |
| 真实同步双目数据及相机参数 | 相机到货后采集；现有 125 对视频导出是单目复制，不能做三维精度验收 |
| 已知格长的标定板、25～40 对覆盖视场的棋盘、独立空间检查点 | 相机锁焦并固定基线后，供 B 建立米制标定和世界坐标 |
| C 实际三类模型、预处理/类别/版本/许可说明 | 供迟到语义、球身份与事件联调；原始权重采用团队有权访问的存储 |
| 厂商 DMA/DDR3L/PCIe SDK、驱动/IP 接口和 AFH03 设备 | 到货后走设备适配入口；受限 SDK 不上传 Git/公开附件 |
| A/B 的草案技术复核与最终审批 | 复核帧启动、元数据、ROI 填充、Mask 位序及量化；蒲公英批准后绑定硬件协议 |

这些材料未在本机取得，本次上传提供软件接入与可复现证据。真实数据、完整 B/C 集成及上板验收另行记录。
