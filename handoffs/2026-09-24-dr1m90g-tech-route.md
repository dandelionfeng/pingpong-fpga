# 任务交接

- 任务编号/负责人：2026-09-24 MLK-F3P-DR1M90G 技术路线 / Codex。
- 基准提交号/工作分支：8f94786 / codex/dr1m90g-tech-route-20260924。保留切换前已有的修改及未跟踪文件；未提交或推送。
- 当前目标与不包含的范围：阅读根目录《技术路线.pdf》，按原文编号连续段落的文风，新建 DR1M90G 平台的处理管线说明。重点发挥内置 CPU 与 NPU；无表格、图片、具体算法。依据用户最新指示采用独立采集与软件时间校准，不以硬件同步触发为前提。本次不做硬件或代码实施。
- 允许修改的文件：根目录《技术路线_MLK-F3P-DR1M90G.docx》、本交接；生成脚本和 QA 中间文件位于已忽略的 tmp/dr1m90g-tech-route/。
- 输入输出/依赖的接口版本：已读取 README、实施规划、接口与验收契约、实施前待确认项及 2026-09-23 最新任务交接，以用户提供的《技术路线.pdf》为本次写作参照。本方案独立存在，不变更现有接口、模型输入、坐标系或规则阈值，不冻结新协议。旧契约中的硬件曝光 pair_id 语义不能直接用于软件时间配对。
- 环境与复现命令：使用 bundled Python `C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`，执行 `-X utf8 tmp/dr1m90g-tech-route/build.py`；PowerShell 执行 `& 'tmp/dr1m90g-tech-route/export.ps1'`，以独立隐藏 Word COM 实例只读打开文档并导出 QA PDF；使用 bundled Poppler 的 `pdftoppm.exe -r 125 -png tmp/dr1m90g-tech-route/review.pdf tmp/dr1m90g-tech-route/page`；相同 Python 执行 `-X utf8 tmp/dr1m90g-tech-route/qa.py`。
- 已执行检查及真实结果：读取参考 PDF 两页并逐页查看；核对本地安路赛道指南物理第 12—13 页的板卡规格，与安路官方 DR1 产品页交叉核查 CPU、NPU、AXI/DMA。文档为 2 页、11 个实际编号段落、0 表格、0 图片、1 个硬件资料超链接；全部正文均出现在 Word 导出的 PDF 中。最终两页 PNG 均已目视检查，无裁切、重叠、标题装饰线或段落断裂。原《技术路线.pdf》SHA-256 前后相同：5DA9E6403B02033D37F1263943C4D991E3E4A1E0C80123C88D0CC3F6AA25FB75。最终 DOCX SHA-256：1b8521dcd97098a9305b2478085accfa9cb5d42e056b238d4dc4a7d554a1d00b。
- 未执行检查、阻塞与所需硬件：标准 render_docx.py 实际执行后因缺少 soffice.exe 失败，改用 Word COM 导出和 Poppler 渲染完成 QA。未取得并运行 DR1 NPU SDK、转换目标模型、核对实际相机接线或执行任何板级测试。官方 NPU Wiki 本次无法通过网页工具访问，因此正文只表述使用配套工具链，未指定未经验证的转换命令、算子或量化格式。未承诺实际帧率、准确率与端到端延迟。
- 修改文件与设计理由：新增 DOCX 与本交接。采用 FPGA 采集/预处理/局部裁剪、内置 NPU 目标检测定位、双核 CPU 跟踪/几何测量/阶段分析/调度的板内协同方案。大范围搜索与局部定位交替安排，保留静止持球目标、手球局部上下文和目标丢失后的重新搜索；规则判断与测量质量分开。CPU 对任务分工并按阶段安排辅助识别，避免仅把 NPU 当作 Ball/Non-Ball 分类器。模型结构、具体算法与性能参数均未展开。
- 下一步及验收条件：如团队选用此板，由 A 核对板卡与双路相机接入条件，由 B/C 先验证官方 PS–PL 数据通路和内置 NPU 示例，再用实际球/手/拍样本评估模型支持范围与测量质量。实际更改协议或模型契约前需 A/B/C 评审。交付文档已完成文件与排版验收，方案尚未经过真实硬件验证。

资料核验入口：

- [安路 DR1 官方产品资料](https://www.anlogic.com/product/fpga/saldragon/dr1)：核验双核处理器、片内 NPU、PS–PL AXI 与 DMA；不能把系列其他型号的 MIPI D-PHY 能力直接套给 DR1M90G。
- 项目目录《全国大学生嵌入式芯片与系统设计竞赛'2026FPGA赛道选题指南-安路科技.pdf》第 12—13 页：MLK-F3P-DR1M90G 板卡、双核 Cortex-A35、NPU、DDR、显示与 FEP 扩展资料。相关页内仍保留 2025 页眉，本次仅用于平台硬件资料，不据此判定赛题或赛程。
- [安路官方 NPU 资料指引](https://tech.anlogic.com/index.php/Category12?cate=15&cates=38)：官方 FAQ 提供 NPU Wiki 入口，Wiki 内容本次未成功读取。
