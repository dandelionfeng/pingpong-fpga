# 任务交接

- 任务编号/负责人：AFH03-MONOCULAR-MONTH-TEAM-PLAN / Codex，面向蒲公英及两位队友。
- 基准提交号/工作分支：8f94786 / codex/afh03-month-team-plan-20260927。由当前方案分支新建，保留已有未提交修改；未提交或推送。
- 当前目标与不包含的范围：按用户提供的桌面《技术路线_AFH03与SC130GS单目神经网络测距方案.pdf》编写一个月三人分工及三份职责说明。只新增文档和交接，不改技术路线原件、旧规划、RTL、模型或正式接口。
- 允许修改的文件：项目规划/AFH03单目方案一个月分工/ 下四个新建 DOCX、本交接；制作和 QA 文件放 tmp/afh03-team-plan/。
- 输入输出/依赖的接口版本：主线为 AFH03-AFC03、单颗 SC130GS、RK3576J、板内 PCIe、神经网络深度与球径几何校验；机位 1.3～1.5 米，240 fps RAW10 为目标，120 fps 为初期联调工作点。旧主规划与契约仍保留原版本。新文档列出接口语义、黄金样例和 A/B/C 第一周评审责任，不冻结新的二进制布局、量化参数或空间角度阈值。
- 环境与复现命令：Bundled Python 为 C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe。在 C:/FPGA competition 执行 `& '<上述Python>' -X utf8 tmp/afh03-team-plan/build.py`、`& tmp/afh03-team-plan/export.ps1`、`& '<上述Python>' -X utf8 tmp/afh03-team-plan/qa.py`。export.ps1 使用独立隐藏 Word COM 实例，只读导出内部 QA PDF；qa.py 使用 pypdf 与 pypdfium2 检查文字并生成每页 PNG。
- 已执行检查及真实结果：四份最终 Word 均为 4 页，共 16 页；最终渲染全部逐页检查，正文和表格零缺失，参考链接共 16 个嵌入实例；各文档“不能、不作为、禁止、不得”均为零。修复默认 Word Title 样式蓝色下划线并重新导出、复核。README、实施规划、旧接口契约、待确认项、原路线 Word 和用户提供的 PDF 共六个源文件 SHA256 全部保持一致。数值依据原技术路线并重算纯载荷，性能和误差作为目标标明。
- 未执行检查、阻塞与所需硬件：未训练、转换或运行模型，未执行 RTL 仿真、TD 综合布线或上板。documents/render_docx.py 已实际尝试，因环境缺少 soffice.exe 失败；使用 Word COM 与 pypdfium2 完成替代渲染 QA。模型准确率、120/240 fps 完整帧率及测量误差均需后续实测。
- 修改文件与设计理由：00_三人分工与一个月实施安排.docx 给出 9月28日至10月27日的四周节点和两天收尾；01_A_FPGA采集缓存与传输职责说明.docx 说明采集、RAW10、DDR、ROI、DMA、记录与显示；02_B_FPGA预处理与三维测量职责说明.docx 说明搜索 RTL、标定、轮廓圆锥、网络深度转三维、轨迹与事件；03_C_AI模型训练与部署职责说明.docx 说明检测、距离回归、数据划分、量化、双模型调度与 DA3 对照。采用正向工作和质量条件，分散采集、标注与验证负担，每份包括可点击资料链接。
- 下一步及验收条件：三人先阅读总安排及各自职责说明，确定 A/B/C 姓名和第一周接口评审；A 提供一份真实或合成帧包，B 提供标定及已知球心 Zc 样例，C 用同一输入完成最小训练与 RKNN 转换探路。第一周出口为像素、坐标、时间、单位和版本语义一致的黄金样例。

QA 文件：tmp/afh03-team-plan/qa-report.json；源文件基准：tmp/afh03-team-plan/source-hashes-before.json。在线入口已核查 OpenCV、RKNN Model Zoo/Toolkit2、MobileNetV2、DA3 官方仓库与模型卡；平台参数按本地指南物理第 9～11 页核对。大文件、厂商受限资料、模型权重和原始视频按本地清单管理。

接手者先阅读 AGENTS.md、当前规划和本交接；文档中的计划与目标按实际测试结果更新验收记录。
