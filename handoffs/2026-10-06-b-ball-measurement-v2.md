# B 局部球心测量 v2 任务交接

日期：2026-10-06。适用 AFH03 USB 同步双目路线 2.5 和 B 最新个人说明；范围为第二部分中的局部测量、帧身份和质量/预测补测。

- 任务编号/负责人：B-part2-v2 / B（cluepiggie）。
- 基准提交号/工作分支：打包目录无 Git 元数据，基准提交号未取得；建议工作分支 `codex/b-ball-measurement`，目标 `main`。正式上传者在 PR 登记实际基准。该核心接收 decoded Mask，不调用第一部分 RTL，因此单独复现不依赖第一部分 PR 合并；系统联调仍需 A 的输入/缓存和同帧 Mask。未创建分支、提交、推送或合并。
- 当前目标与不包含的范围：完成局部区域选择与误检拒收、固定 ROI/帧身份、质量与外部预测位置补测。本轮不实现 YOLO、标定/三维、Kalman 或发球事件，不声明完整第二部分或硬件验收完成。
- 允许修改的文件：`software/pc_pipeline/ball_measurement/`、`tools/fixtures/ball_measurement_v2_*`、本轮验证报告及 `reports/ball_measurement_v2/2026-10-06/`、本交接。上传时在 `handoffs/README.md` 加本交接链接，保留既有入口和历史内容。A/C 源码、第一部分 RTL 和现行方案 Word/PDF 未修改。
- 输入输出/依赖的接口版本：640×360 decoded CV_8UC1 Mask 与同帧 1280×720 灰度原图，正式入口 `measure_eye` / `measure_pair`。校验 pair_id、eye、ns 采样时间、mode/config/calibration 与 reference_id；输出独立的 observed/predicted/invalid、固定 256×256 ROI、64×64 局部窗口、有效范围及质量。`b-measure-v2-draft` 是待评审的进程内 C++ 草案，未冻结 PCIe 布局或共享阈值；调用者需重编译。预测位置须由后续跟踪模块投影到当前眼、当前采样时间。
- 环境与复现命令：MSVC 19.43.34808.0、Windows SDK 10.0.22621.0、CMake 3.30.5-msvc23、Ninja 1.12.1、OpenCV C++ 4.10.0；Python 3.12.14、NumPy 1.26.4、opencv-python 4.10.0.84。按[模块 README](../software/pc_pipeline/ball_measurement/README.md)执行 build_and_test.bat → v2 fixture → C++ CLI → v2 score；Python 依赖已固定在 requirements 文件。
- 已执行检查及真实结果：Windows C++17 Release 构建/链接，3/3 CTest、42 个检查（12 选择 / 16 身份与 ROI / 14 质量与预测）；54/54 文件场景通过，含预期拒收。35 个清晰合成场景球心误差 P95=0.0725405931 px；随机种子 106006。C++ 不读取隔离 truth，评分器单独读取；固定场景开发期间使用过，C 尚未独立复核。详见[验证报告](../reports/第二部分_球心测量_v2验证_2026-10-06.md)和[文本证据](../reports/ball_measurement_v2/2026-10-06/README.md)。
- 未执行检查、阻塞与所需硬件：工作目录缺少 Git 元数据、仓库 tools/check_repo.py 和仓库 tests，因此未运行正式仓库 `--staged` 检查或仓库 unittest。最终包使用附件仓库检查器逐文件检查，不能替代上述检查。Linux、A/C 联调、C 独立复核、真实许可图像/相机与板端吞吐未验证；本 PC 模块未执行 RTL 仿真、目标综合或上板。拿到真实输入后评审阈值与鲁棒性。
- 修改文件与设计理由：只对选中局部连通域计算 moments；两极性与周边背景对比，拒收低对比/异常尺度/形状/边界/歧义；ROI replicate 补齐，Otsu 和区域统计排除填充像素；失败和元数据错误先拒收。预测只作为重新搜索入口，找到真实区域才输出 observed，无球保持 prediction-only。保留每次尝试、区域与 Sobel 等质量证据。
- 下一步及验收条件：A 填真实 FrameStamp、同眼 reference_id 和成功/失败状态，核对版本并接入正式入口，技术复核接口与 ROI 兼容影响；C 使用独立 truth 复核并扩大真实困难样例。轻度遮挡的 moments 可能有偏差（例：真值 640,360，输出约 637.95746,360），必须携带 reduced 质量。后续几何完成极线身份配对/三角测量，跟踪提供预测；本模块双眼结果尚不证明是同一球。最终审批与合并由 FengFengKang（蒲公英）确认；本包不记录尚未发生的批准。
