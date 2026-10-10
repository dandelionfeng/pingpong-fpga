# B 第三部分 v2 新基准复现记录

日期：2026-10-10。负责人：B / cluepiggie。基准 main `fe7af549464b290b2573199a1cf5a00ebf4432a5`，新分支 `codex/b-trajectory-events-v2-path-fix`。依据当前技术路线2.1、2.7、2.8和B职责，新增独立三维/跟踪/事件核心并修复旧PR的目录与复现阻塞。

本轮从已登录GitHub下载main ZIP，核对ZIP comment等于上述提交号；解压到新目录，叠加本次B3源码，B2沿用main同级目录原文件。新BuildDirectory和OutputDirectory此前不存在，没有复制旧构建产物或第二部分目录冒充成功。下载快照没有上游Git历史；本地初始化的Git仅用于差异/暂存检查，不能把其合成提交号当上游源码号。

## 实际命令与结果

从新源码目录执行：

```powershell
& '.\software\pc_pipeline\trajectory\run_validation_v2.ps1' `
  -Python 'D:/FPGA competition/.venv/Scripts/python.exe' `
  -OpenCVDir 'D:/FPGA competition/.tools/opencv-4.10.0/opencv/build/x64/vc16/lib' `
  -BuildDirectory '.\build\b-trajectory-release' `
  -OutputDirectory '.\output\b-trajectory-v2-20261010'
```

退出0并输出 PART3_V2_VALIDATION_PASS。Release配置/编译通过；8/8 CTest（B3 62项、B2 42项）；84/84文件场景，包括按预期unknown/cancelled；棋盘留出4/4及6/6；88事件证据窗口、12图表。原始输入、真值、完整图片与结果仍在本机output/b-trajectory-v2-20261010，此次不上传结果ZIP。

MSVC19.43.34808.0、SDK10.0.22621.0、CMake3.30.5-msvc23、Ninja1.12.1、OpenCV C++4.10.0；Python3.12.14、NumPy1.26.4、opencv-python4.10.0.84、matplotlib3.9.2。软件参数、命令、日志哈希在RUN_MANIFEST.json，默认参数见CONFIG_DEFAULTS.json；B2依赖原字节哈希见DEPENDENCY_SHA256.json。

## 可审阅证据

- configure-output.txt、build-output.txt、ctest-output.txt、validation-output.txt：实际新目录运行日志；按UTF-8转换保存，原文件字节哈希另记录。
- score-v2.json、board-score.json、board_broad-score.json：实际文件/棋盘留出评分，含失败检查与各场景指标。
- board_calibration.json、board_broad_calibration.json：本次生成棋盘估计参数，仅用于合成练习，不能作为真实相机参数。
- INPUT_SHA256.json、SCENARIO_MATRIX.json：固定输入/隔离truth及场景范围；被测CLI不读取truth。
- SOURCE_SHA256.json：本次交付文件原字节，不包含清单自身；第三部分专用清单不覆盖根SOURCE_SHA256.json。
- repository-checks.txt：下载main快照叠加本次源码后的本地暂存检查与unittest。GitHub正式CI另外以PR head状态为准。

全部属于B开发合成回归，C未冻结或独立复核。检测框为synthetic replay，Mask是人工提示，没有接通A七级或实际模型的声明。像素回放理想几何误差与人工图像链路误差须分开看；图像场景的三维P95仍约毫米到厘米量级，不能推断真实精度达标。误差包络不是经统计校准的置信区间，不自动判罚。

## 未执行与后续入口

A的pipeline_b_module适配、在线/Qt联调，C真实YOLO/RKNN与独立评价，公开棋盘练习、实物OV9281锁焦标定/同步/米制核验，Linux/ARM、RTL仿真/TD综合/上板均未执行。本轮限PC独立核心及提交复现修复；缺硬件的内容等待实物，软件联调另按A/C入口推进。构建及调用见software/pc_pipeline/trajectory/README.md，负责人步骤见handoffs/2026-10-10-b-trajectory-v2-path-fix.md。

未修改B1/B2算法、A/C源码、技术路线或Word/PDF，未上传旧BPart2、生成工程、二进制、权重或视频。共同协议/判罚参数仍为草案，最终审批/合并由FengFengKang确认。
