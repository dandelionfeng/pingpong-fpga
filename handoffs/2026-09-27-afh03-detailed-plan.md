# 任务交接

- 任务编号/负责人：AFH03 双 NV1100M 详细技术方案 / Codex。
- 基准提交号/工作分支：8f94786 / codex/afh03-detailed-plan-20260927。保留进入任务前全部未提交修改，未提交或暂存其他文件。
- 当前目标与不包含的范围：创建详细 Word 技术方案，按步骤说明算法、功能及 FPGA、NPU、CPU 数据流。用户最新要求默认摄像头可接入，删去接口兼容性审查；不包含人员分工、RTL 修改、模型实现或上板验证。
- 允许修改的文件：新增技术路线_AFH03与双NV1100M详细方案.docx、本交接；制作与验证文件仅放 tmp/afh03-detailed-plan。
- 输入输出/依赖的接口版本：读取 README、项目实施规划、接口与验收契约、实施前待确认项及 AFH03 图像管线交接；本方案是独立规划文档，不修改或冻结现有接口协议、坐标契约和判罚阈值。实现接口前仍应按 AGENTS.md 评审。默认双 NV1100M 接入 FPGA，CPU/NPU 使用 AFH03 上 RK3576J。遵循用户本次明确选择，不将旧 RK3566 方案写入本文件。
- 环境与复现命令：Python 为 C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe。用该解释器运行 `-X utf8 tmp/afh03-detailed-plan/build.py`；PowerShell 运行 `& 'tmp/afh03-detailed-plan/export.ps1'`；再用同一解释器运行 `-X utf8 tmp/afh03-detailed-plan/qa.py`。
- 已执行检查及真实结果：build.py 成功生成文件；QA 确认 19 个步骤、无表格和图片、原简版 SHA256 不变。调用 documents/render_docx.py 时因缺少 soffice.exe 失败，随后 Microsoft Word COM 导出 PDF 成功，pypdfium2 渲染为 5 页 PNG，逐页目视检查通过。已去除默认标题蓝色边框和副标题斜体。最终 QA 见 tmp/afh03-detailed-plan/qa-report.json。
- 未执行检查、阻塞与所需硬件：未运行 RTL 回归、综合或上板；本任务没有代码变更。本文所列新增算法与性能预算属于方案，不能视为实现完成或实测性能。没有妨碍本次文档交付的阻塞。
- 修改文件与设计理由：新增 5 页 Word，保留旧简版。FPGA 负责滤波、差分与背景提取、游程连通域、当前帧 DDR 回读 ROI 与预测流式 ROI；NPU 负责全景检测、球心热力图和阶段性手部分割；CPU 负责跟踪、软件时间校准、标定、三维重建、事件及测量。正文不放采购与兼容性清单。
- 下一步及验收条件：实施入口为新方案第 19 步，结合 handoffs/2026-09-24-afh03-image-pipeline.md 确认可复用 RTL 范围，先完成双路采集与现有预处理，再实现候选、缓存和传输；每阶段按文中功能验证，真实记录延迟、丢帧和测量误差。

技术来源已核对 OpenCV 官方 calib3d 文档、Rockchip RKNN Toolkit2 与 Model Zoo YOLOv8 说明；ITTF 2026 Statutes 官方 PDF 第 41 页包含 2.6.2 的 16 cm 与 near vertically 条款。文档末尾提供链接；本地平台资料用于板卡路线背景。未使用未验证的 NV1100M 分辨率、帧率或像元尺寸。

旧版技术路线_MLK-AFH03-AFC03-2GB.docx SHA256：455229290b960992c4b42b1e3a3f4462e3cd020eb74e244981c815d115ef7c2d。

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖上一段聊天隐含的信息。
