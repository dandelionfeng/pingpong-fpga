# 任务交接

- 任务编号/负责人：2026-09-24 MLK-AFH03-AFC03 技术路线 / Codex。
- 基准提交号/工作分支：8f94786 / codex/afh03-afc03-tech-route-20260924。保留用户与前序任务已有修改；未提交或推送。
- 当前目标与不包含的范围：按用户指定的 MLK-AFH03-AFC03-2GB LPDDR4X+32GB EMMC 配置，另写一份技术路线 DOCX，沿用《技术路线.pdf》的编号连续段落文风，发挥 CPU、NPU 能力。只说明管线，不含具体实现算法、表格或图片；双目采用软件时间校准。本次不开发硬件、模型或驱动。
- 允许修改的文件：根目录《技术路线_MLK-AFH03-AFC03-2GB.docx》、本交接；构建与 QA 文件在忽略目录 tmp/afh03-afc03-tech-route/。未更改前两版技术路线或现有项目规划。
- 输入输出/依赖的接口版本：已读取 README、现行规划和契约、待确认项、上一版交接及本地安路指南的平台三资料。本方案按用户新要求独立设计，不沿用旧硬件曝光 pair_id 语义，不改写或冻结既有接口、模型输入、坐标系及规则阈值。
- 环境与复现命令：以 `C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` 执行 `-X utf8 tmp/afh03-afc03-tech-route/build.py`；PowerShell 执行 `& 'tmp/afh03-afc03-tech-route/export.ps1'`，Word COM 隐藏实例只读打开并导出 QA PDF；bundled Poppler 执行 `pdftoppm.exe -r 125 -png tmp/afh03-afc03-tech-route/review.pdf tmp/afh03-afc03-tech-route/page`；相同 Python 执行 `-X utf8 tmp/afh03-afc03-tech-route/qa.py`。独立 build.py 已生成，复现无需运行引用上一任务排版代码的 prepare.py。
- 已执行检查及真实结果：本地指南物理第 9—11 页核验 PH1A90SEG324、RK3576J、四核 A72+四核 A53、2GB LPDDR4X、32GB eMMC、FPGA 侧 256MB DDR3L、板内 MIPI/PCIe 互联及 HDMI。核对官方 RKNN-Toolkit2 和 librga 对 RK3576 的支持。最终 DOCX 共 2 页、11 个编号段落、0 表格、0 图片、3 个资料链接。全部正文在 Word 导出 PDF 中完整存在，编号段落未跨页拆开。最终两页 PNG 已逐页目视检查，无重叠、截断或标题装饰线。最终 DOCX SHA-256：455229290b960992c4b42b1e3a3f4462e3cd020eb74e244981c815d115ef7c2d。
- 未执行检查、阻塞与所需硬件：render_docx.py 因缺少 soffice.exe 失败，已通过 Word COM 与 Poppler 完成替代排版验收。未验证相机扩展板引脚、双路采集、板内 PCIe 驱动/DMA、RKNN 模型转换、RGA 与编码器实际运行、内存峰值或整机性能。瑞芯微官方 Brief Datasheet 搜索可定位，但 PDF 网页工具读取超时；板卡具体内存与互联事实以已读取的本地指南为依据，不据网络摘要承诺性能。
- 修改文件与设计理由：新建 DOCX 和本交接。方案采用 FPGA 前端采集与缓存，经板内 PCIe 传至 RK3576J；NPU 执行场景多目标识别、高频局部球心定位和按阶段安排的手/拍识别；CPU 大核优先跟踪、几何测量和事件分析，小核主要承担采集管理与后台服务。RGA 分担缩放、格式转换和裁剪，编码器承担回放视频支路；测量保留原始图像细节。区分 FPGA 缓存、2GB 运行内存和 32GB 存储，限定循环缓存与事件录像，避免无界增长。选板不等于参加官方选题三，本次没有擅自增加该选题的全部硬性交付项。
- 下一步及验收条件：团队选择本方案后，A 核实相机到 FPGA 的采集扩展与引脚，B 核实 PCIe 双向控制/数据传输及 RK3576J 驱动，C 用球/手/拍实际样本验证 RKNN 部署和识别测量质量。先测实际内存峰值、吞吐和关键阶段漏检，再确定输入规模与调度频率。接口或模型契约变更需相关负责人评审。本文为方案与文档交付，不代表上板验收。

资料与保真记录：

- 本地《全国大学生嵌入式芯片与系统设计竞赛'2026FPGA赛道选题指南-安路科技.pdf》第 9—11 页为板卡参数依据；第 19 页误写“四核 A55”，本方案采用平台参数页及瑞芯微资料一致的四核 A72+四核 A53。部分平台页仍有 2025 页眉，本次不据其确认赛程。
- [米联客平台发布页](https://www.uisrc.com/t-6607.html)。页面正文主要是图片，未据未读取图片声称新增接口细节。
- [RKNN-Toolkit2 官方仓库](https://github.com/airockchip/rknn-toolkit2)：明确支持 RK3576 系列及模型转换和板端推理。
- [librga 官方仓库](https://github.com/airockchip/librga)：RGA 二维图像加速功能与 RK3576 支持。
- 原《技术路线.pdf》SHA-256 保持 5DA9E6403B02033D37F1263943C4D991E3E4A1E0C80123C88D0CC3F6AA25FB75；前版《技术路线_MLK-F3P-DR1M90G.docx》保持 1B8521DCD97098A9305B2478085ACCFA9CB5D42E056B238D4DC4A7D554A1D00B。
