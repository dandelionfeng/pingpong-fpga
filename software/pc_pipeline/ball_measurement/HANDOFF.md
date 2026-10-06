# B 第二部分 v2 任务交接

- 任务编号/负责人：B-part2-v2 / B（cluepiggie）。
- 基准提交号/工作分支：本机目录无 Git 元数据，未建立分支或提交。建议 `codex/b-ball-measurement`，正式上传前从最新已评审 origin/main 核对；不宣称已合并第一部分或已有 PR。
- 当前目标：局部球区域选择与误检拒收、固定 ROI 与帧身份、质量判断与预测位置补测。三维标定、Kalman、事件和模型不在本轮。
- 允许修改：software/pc_pipeline/ball_measurement/，tools/fixtures/ball_measurement_v2_*，本轮 reports 与 _deliveries；A/C、方案 PDF/Word 和第一部分 RTL 未修改。
- 输入输出/依赖版本：640×360 decoded CV_8UC1 Mask 与同帧 1280×720 灰度图；同 pair_id、eye、采样时间、mode/config/calibration；逻辑草案 b-measure-v2-draft。输出 observed/invalid 与独立 predicted，ROI 原点/补齐/有效范围，选中区域、质量及拒收理由。
- 已执行：Windows C++17 Release 编译、3/3 CTest（42 检查）、54 个文件场景及隔离真值评分；35 个清晰球场景 P95 0.07254 px。C++ 程序不读取 truth，C 尚未独立复核。
- 环境与复现：README 中 build_and_test.bat → v2 fixture → ball_measurement_cli → v2 score。工具：MSVC 19.43.34808.0，SDK 10.0.22621.0，CMake 3.30.5-msvc23，Ninja 1.12.1，OpenCV C++ 4.10.0；Python 版本见结果包 tool-versions.txt。
- 未执行：仓库 `python tools/check_repo.py --staged` 和仓库 unittest（此目录无 .git、检查脚本及仓库 tests），Linux、A/C 联合复核、真实图像/相机和设备。需在正式仓库复制后执行要求的检查。
- 修改与理由：局部二次连通域阻止多物体总质心；两极性+背景环对比避免单像素极性；低对比、尺度、形状、边界和歧义拒收；固定 ROI replicate + valid mask 排除填充统计；预测只做搜索，不伪造实测；无预测和多个同样 plausible 区域保留 unknown/invalid。
- A 的接手：为 FrameStamp 填真实源帧元数据，解包 Mask 后保留 reference_id 和成功/失败状态，配置版本一致；按 measure_eye 或 measure_pair 调用。核对 Config 门限、ROI 补齐和接口兼容影响；位序/PCIe 字段另评审。旧像素函数无身份校验只用于测试。
- C 的接手：读取 inputs 与独立 truth，对输出 JSON 复核；实际模型模式和本轮像素生成模式分开。不把观测输出作为自己的真值。
- 后续验收条件：评审接口后接入 A，扩大真实公开图/困难样例，Linux 构建与独立 C 评分；三维极线/身份配对和 Kalman 再接。Reduced 遮挡 moments 可能有偏，必须携带质量进入后续模块。

