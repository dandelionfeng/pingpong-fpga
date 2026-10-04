# 任务交接

- 任务编号/负责人：2026-10-02 USB 同步双目 A/B/C 个人详细工作表；Codex。
- 基准提交号/工作分支：`c638158281dff65ec9a7750ac85ae4b4d5f9dfcf`；`codex/usb-stereo-personal-worktables-20261002`。开始时已有技术路线、总分工、两份交接和 rk3566 占位文件删除等未提交状态，均保留。
- 当前目标与不包含的范围：细化三人的独立职责文档，提供具体操作、交付与对接、关键步骤解释、四周推进表、上手顺序、排错和资料链接。本次工作限定于三个个人文档及其已有 Markdown 对应稿；技术路线、总分工、实施代码及全局入口维持开始时的文件状态。
- 允许修改的文件：以下六个文件，以及本交接。
  - `项目规划/AFH03_USB同步双目方案一个月分工/01_A_USB采集与FPGA链路职责说明.docx`
  - `项目规划/AFH03_USB同步双目方案一个月分工/01_A_USB采集与FPGA链路职责说明.md`
  - `项目规划/AFH03_USB同步双目方案一个月分工/02_B_FPGA视觉与三维测量职责说明.docx`
  - `项目规划/AFH03_USB同步双目方案一个月分工/02_B_FPGA视觉与三维测量职责说明.md`
  - `项目规划/AFH03_USB同步双目方案一个月分工/03_C_AI模型训练与部署职责说明.docx`
  - `项目规划/AFH03_USB同步双目方案一个月分工/03_C_AI模型训练与部署职责说明.md`
- 输入输出/依赖的接口版本：以 2026-10-02 的 USB 双目技术路线 Word、总分工 Word/Markdown 和 `handoffs/2026-10-02-usb-stereo-integrated-team.md` 为依据。84°镜头，YUY2 2560×720@60，每眼 1280×720，基线 150～200 mm；RK 保存原图并生成双眼 640×360 GRAY8，FPGA 运行高斯→帧差→阈值→腐蚀→膨胀→膨胀→腐蚀并返回两张 1 bit 掩膜。局部 ROI、球心与三维在 RK 处理，YOLOv8n 三类身份推理异步运行。每对图一次 H2C、一次 C2H。字段布局与位顺序仍按总分工由 A/B/C 共同评审，个人表只是实施安排。
- 环境与复现命令：Windows PowerShell，已有 Microsoft Word COM，bundled Python 的 python-docx/pypdfium2。排版检查沿用 Word 只读导出临时 PDF、pypdfium2 以 2 倍比例生成页图的替代流程；当前环境缺少 LibreOffice。生成、检查与备份位于忽略目录 `tmp/personal-worktables-20261002/`。

```powershell
$taskPython = 'C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& 'C:\FPGA competition\tmp\personal-worktables-20261002\render_worktables.ps1'
& $taskPython 'C:\FPGA competition\tmp\personal-worktables-20261002\render_pages.py'
& $taskPython 'C:\FPGA competition\tmp\personal-worktables-20261002\verify_worktables.py'
git diff --check
```

- 已执行检查及真实结果：三份 Word 只读导出成功；A 5 页、B 4 页、C 5 页，共 14 页，最终页图均逐页按原始分辨率检查，表格无裁切、重叠或孤立表头。每人 9 项任务、3 张表、4 周加收尾共 5 行阶段安排；所有段落和表格单元格均与对应 Markdown 匹配。三份引用条目数为 6/6/5，可点击外链数为 4/5/8。原有图片资源保持一致，页码字段保留。开始时 148 个文件路径的 SHA-256 对照确认只有允许的六份文件内容改变，其余文件及原有删除状态保持；本交接是新增文件。带宽纯载荷和位宽复核：H2C 27.648 MB/s，C2H 3.456 MB/s，掩膜 57,600 字节/对，高斯累加含舍入可用 12 位。`git diff --check` 通过。
- 未执行检查、阻塞与所需硬件：本次为文档编辑，未执行真实相机采集、当前七级 RTL 仿真/综合/上板、PCIe 吞吐、模型训练与板端推理、功耗测试；需要后续 A/B/C 在 AFH03、相机和训练设备上实施。调用预算与理论带宽没有写成实测结果。没有新增文档编辑阻塞。
- 修改文件与设计理由：A 承担 USB/V4L2、原图引用、灰度缩图、FPGA 前三级/前帧 DDR、DMA/顶层及显示回放；B 承担 FPGA 四级形态学/打包、RK 连通域/Otsu/图像矩、标定/三角测量/世界坐标、卡尔曼与三个关键点；C 承担数据划分、灰度三通道/letterbox、YOLOv8n、Rockchip 适配 ONNX/INT8 RKNN、C++ 后处理和异步身份。三人共同采集、交叉标注和联调以分担工作量。补充 V4L2 驱动缓冲归还后的生命周期、校正相机坐标旋回原左相机再转世界、NPU 总调用预算、同算法 CPU 对比及官方资料链接。B 的静态联调采用空背景前帧和放球当前帧，使帧差有有效输入。
- 下一步及验收条件：A 从 A1/A2 确认真实 USB 和 PCIe 工程并提供成对原图/搜索图；B 从 B1/B2 准备四级中间图、打包结果与 RTL；C 从 C1/C3 确定三类标签、输入变换和对应样例。首周三人使用相同输入评审帧号、位序、边缘规则、ROI 原点和模型框逆变换，再依据各自周表推进。验收记录写在实施交接中，使用实际运行结果。

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖上一段聊天隐含的信息。全局旧入口中仍有历史参数和职责内容，本次个人表以这里列出的最新技术路线与总分工为依据。
