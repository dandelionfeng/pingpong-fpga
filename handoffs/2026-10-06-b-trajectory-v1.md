# B 第三部分初版交接

- 任务编号/负责人：B-part3-v1 / B（cluepiggie），2026-10-06。
- 基准提交号/工作分支：本目录无 Git 元数据，提交号未取得；建议 `codex/b-trajectory-events`。依赖第二部分 `software/pc_pipeline/ball_measurement/` 当前 v2 源码；第二部分若未合并，上传时说明实际依赖 PR/基准，不覆盖团队最新源码。本轮无 GitHub 写操作。
- 当前目标与不包含的范围：完成三维、Kalman/预测 ROI、事件/高度拟合可运行初版和真实 PC 验证。不声明 P5/P6/P8/P9 全部完成，不训练模型或处理真实硬件。
- 允许修改的文件：新增 `software/pc_pipeline/trajectory/`、`tools/fixtures/trajectory*`、本轮 reports、handoffs 与本地 `_deliveries/part3_v1_validation`。第二部分源码、第一部分 RTL、A/C 代码、路线 Word/PDF 均不改。
- 输入输出/依赖的接口版本：FrameStamp 与 PredictionHint 复用第二部分，新增 `b-trajectory-v1-draft`、`b-calibration-v1-draft`。每眼 1280×720 灰度，世界 X 台宽/Y 台长/Z 向上，米制；正式几何只接受同帧实际球心。标定 unit=square 不得用于米制结果。观测/滤波/预测及 source_pair_id 分栏。
- 环境与复现命令：MSVC 19.43.34808.0、SDK 10.0.22621.0、CMake 3.30.5-msvc23、Ninja 1.12.1、OpenCV C++ 4.10.0；Python 3.12.14、NumPy 1.26.4、opencv-python 4.10.0.84。运行模块 `run_validation.ps1`；单步命令见 README。Python 仅生成/评分/画图，核心 C++。
- 已执行检查及真实结果：40 个新增 C++ 检查，42 个第二部分回归，7/7 CTest；20/20 文件场景；12 对生成棋盘标定，另 4 对姿态检查通过。源码、配置、输入、结果、版本和实际日志打包；理想几何与图像链路分栏，truth 不进 C++ CLI。C 尚未独立复核。
- 未执行检查、阻塞与所需硬件：真实相机标定、尺度/同步与实物测量，公开棋盘来源练习、实际 C 模型、A 在线队列/缓存联调、Linux/ARM、目标综合/板卡性能。无仓库元数据与检查脚本，不运行或宣称 `check_repo --staged`/仓库 unittest 通过。
- 修改文件与设计理由：严格按 R1ᵀ、Rcwᵀ 恢复坐标；矩阵校验不修改调用方参数；实测 dt/重力和 launch 速度模式切换；异常点门控、三点重捕获；预测只搜索；离线检测框按源帧关联；手分离+连续上行、拍接近+速度折点定义事件区间；有效实际观测稳健拟合，最后持球高度可在区间内细化离手，否则保留中点与包络。
- 下一步及验收条件：A 复核草案接口/元数据，将 MeasurementCore 接到正式输入和有限异步队列；C 提供实际模型结果、可见性、来源帧与独立真值，扩大至规划的 30 发球/10 缺证据/5 异步场景。先深化图像链路误差、遮挡/触拍重捕获和误差包络，再 Linux/真实输入。图像样例抛高偏约 2.73 cm，不能当精度验收通过；矩阵回放和生成棋盘分别报告。现行阈值/共享接口仍待 FengFengKang（蒲公英）最终审批，本交接不记录尚未发生的批准。
