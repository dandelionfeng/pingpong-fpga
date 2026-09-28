# 任务交接

- 任务编号/负责人：AFH03-ROUTE-BEGINNER-EDIT / Codex，面向蒲公英及两位队友。
- 基准提交号/工作分支：8f94786 / codex/afh03-route-beginner-edit-20260927；由上一分工任务分支新建，保留既有修改，未提交或推送。
- 当前目标与不包含的范围：用户明确要求修改原技术路线 Word 并导出新版 PDF，删除否定性表述，适合初学者阅读，对齐最新三人分工和一个月安排。修改范围仅为指定路线、同名 PDF 与本交接，不改硬件代码、模型、旧正式接口和分工文档。
- 允许修改的文件：根目录《技术路线_AFH03与SC130GS单目神经网络测距方案.docx》与同名 PDF；本交接；临时构建、备份和 QA 文件位于 tmp/afh03-route-beginner/。
- 输入输出/依赖的接口版本：依据原 Word 的最新内容及当前四份分工文档。A 负责采集/DDR/ROI/PCIe/接收回放/显示；B 负责搜索 RTL/标定/几何/轨迹/事件；C 负责检测及距离网络/量化/双模型运行。9月28日至10月27日准备：前两周120 fps闭环，第三周依实测评估240 fps，第四周独立验收，最后两天收尾。新单目接口语义仍由 A/B/C 评审和黄金样例确认，未修改正式二进制协议。
- 环境与复现命令：Bundled Python 为 C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe。在 C:/FPGA competition 运行 `& '<上述Python>' -X utf8 tmp/afh03-route-beginner/build.py`，`& tmp/afh03-route-beginner/export.ps1`，`& '<上述Python>' -X utf8 tmp/afh03-route-beginner/qa.py`。build.py 从 tmp 内 original.docx 读取原文件样式并生成新版，重新运行会覆盖指定 Word；export.ps1 用独立隐藏 Word COM 只读导出同名 PDF；qa.py 用 pypdf 和 pypdfium2 核对正文、链接并渲染全部页。
- 已执行检查及真实结果：最终 PDF 共11页，正文与表格内容零缺失，11页最终 PNG 全部逐页检查；验收表已调整为完整一页。Word 保留14个编号技术部分、资料与GPU附录，增加三人职责、术语解释、公式解释、四周安排与协作入口。12类否定式词组审计均为零；10个实际使用的资料超链接；GPU示例通过 AST 语法检查。四份当前分工文档在本次制作前后 SHA256 一致，包含用户对总安排的近期修改。
- 未执行检查、阻塞与所需硬件：GPU示例仅做语法检查，未运行推理、训练、量化或硬件测试。沿用上一任务已确认的 Word COM 替代渲染路径；环境无 soffice.exe。方案中的帧率、误差、参数量和算力均按目标或预算表述，留待板卡、相机、量具和独立样本验证。
- 修改文件与设计理由：指定 Word 原路径更新为初学者说明版，同名 PDF 作为同步阅读版。使用“模块负责什么、数据怎么走、满足什么条件时使用”代替否定式要求；解释 ROI、DDR、DMA、NPU、标定、回归、量化、状态机和误差指标。保留 RAW10/原始ROI、几何与网络选择、原始帧号、三维坐标、质量复核、独立测试等关键技术语义。增加 RKNN Toolkit2 和 MobileNetV2 官方 GitHub 入口，保留原8个外部参考链接。
- 下一步及验收条件：团队先读更新后第1节职责、第13节接口与一个月安排，再进入个人职责说明。A 提供帧包，B 提供标定及球心 Zc 真值，C 做同输入试转换；第一周完成像素、坐标、时间、单位和版本一致的黄金样例。

原 Word 备份：tmp/afh03-route-beginner/original.docx。

最终 Word SHA256：28d4cdabe44567ab375a317b74663a624ed5fb1bdabd8b210fef6b40f562f6ad。

最终 PDF SHA256：039d4881ca73cfd376ccb582bef53d5e0d3bedc353b0fb6bd4adb226dd93c1c5。

QA：tmp/afh03-route-beginner/qa-report.json。PDF 位于工作区根目录，桌面原始附件保留原样。

接手者先阅读 AGENTS.md、当前规划和本交接；文档修改完成不表示模型或上板验收已经完成。
