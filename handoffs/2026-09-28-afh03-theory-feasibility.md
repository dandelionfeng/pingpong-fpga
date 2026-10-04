# 任务交接

- 任务编号/负责人：AFH03-THEORY-FEASIBILITY-20260928 / Codex。
- 基准提交号/工作分支：`8f94786a843eb669f74cbf4eabd46b92cc2bc841` / `codex/afh03-theory-feasibility-20260928`。
- 当前目标与不包含的范围：核对现行 AFH03+SC130GS 单目路线的器件级容量与带宽理论可行性，交付 PDF；本任务不做上板、综合、时序、DMA 或模型性能实测，也不改原技术路线 Word/PDF。
- 允许修改的文件：`output/pdf/AFH03与SC130GS技术路线_理论可行性报告_2026-09-28.pdf`、`tmp/pdfs/build_afh03_feasibility.py`、本交接及 PDF 渲染 QA 临时文件。
- 输入输出/依赖的接口版本：以根目录现行《技术路线_AFH03与SC130GS单目神经网络测距方案.pdf》作为负载条件；以本地竞赛指南 PDF 物理第 9-11 页、安路 PH1A 官方精确型号选型表、思特威 SC130GS 官方 flyer、PCI-SIG 和瑞芯微官方资料作规格依据。未修改正式接口或量化参数。
- 环境与复现命令：`C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -X utf8 tmp\pdfs\build_afh03_feasibility.py`；用 bundled `pdftoppm.exe -r 110 -png <PDF> tmp\pdfs\afh03-report` 渲染检查。
- 已执行检查及真实结果：PDF 成功生成，5 页，110950 字节；逐页渲染检查无裁切或重叠；提取文本含核心 1066 Mb/s、2.132 GB/s、715.653 MB/s、32.440 MB/s；七条在线资料超链接均存在。核心发现：安路官方 PH1A90SEG324 行为 DDR 1066 Mb/s×16 且 MIPI-IO 为“—”，与本地竞赛指南“1866MHz×16bit”冲突；按 1066 重算 DDR 理论峰值 2.132 GB/s。理论示例访问 715.653 MB/s，占峰值 33.6%。
- 未执行检查、阻塞与所需硬件：用户明确只要理论值；AFH03 原理图、该封装引脚、模组 MIPI 连接/外部 D-PHY、板上 DDR 器件及实际控制器速率仍需厂家文件，决定相机直入 FPGA 路线是否成立。
- 修改文件与设计理由：新增五页可行性报告，将精确型号与系列产品规格分开，给出传感器、DDR、PCIe、缓冲和计算的公式及来源；保留现行团队分工与 120 fps 先闭环、240 fps 条件升级的实施顺序。
- 下一步及验收条件：A 向米联客/安路索取 AFH03 原理图、PH1A90SEG324 对应接收通路和 DDR 速率设定；B/C 根据选定通路审查 ROI/模型输入。取得文件后再更新技术路线与接口评审，硬件到位后另做实测报告。

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖上一段聊天隐含的信息。
