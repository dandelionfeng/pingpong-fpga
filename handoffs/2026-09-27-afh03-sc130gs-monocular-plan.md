# 任务交接

- 任务编号/负责人：AFH03-SC130GS-MONO-PLAN / Codex。
- 基准提交号/工作分支：8f94786 / codex/afh03-monocular-sc130gs-20260927。任务开始时由原方案分支新建；保留已有全部未提交修改，未提交或推送。
- 当前目标与不包含的范围：按用户最新选择，新增 AFH03 + 单颗 SC130GS 的单目测量 Word 方案；拍摄距离已更新为 1.3～1.5 米。简化 FPGA、离手与触拍流程，说明硬件预算，并在文末附电脑 GPU 测试方法。不修改 RTL、模型、正式接口契约或旧规划。
- 允许修改的文件：新增根目录《技术路线_AFH03与SC130GS单目测量方案.docx》、本交接；制作及 QA 文件放忽略目录 tmp/afh03-monocular/。
- 输入输出/依赖的接口版本：已读 README、项目实施规划、接口与验收契约、实施前待确认项及 AFH03 交接。新文档遵循用户此次 AFH03 单目指令，既有主路线文件保持原状。第 12 节只有单目接口语义草案，尚未评审冻结，不能直接替换旧 pair_id 或模型输入契约。相机按用户要求默认可接入。
- 环境与复现命令：Python 使用 C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe。依次执行 `& '<该解释器>' -X utf8 tmp/afh03-monocular/build.py`、`& 'tmp/afh03-monocular/export.ps1'`、`& '<该解释器>' -X utf8 tmp/afh03-monocular/qa.py`。build.py 是本次完整文档源；export.ps1 使用独立隐藏 Word COM 实例只读导出 PDF；qa.py 用 pypdfium2 渲染 PNG。
- 已执行检查及真实结果：Word 共 7 页、85 段落、13 个技术步骤与 4 个附录步骤，无表格、无图片；全部正文在导出 PDF 中存在，7 页 PNG 已逐页目视检查。GPU 示例通过 Python 语法检查，未执行推理。计算复核确认 3.6 mm 镜头在 1.3/1.5 米处球径约 27.69/24 px，0.25 px 直径误差对应约 1.17/1.56 cm 深度误差。QA 记录在 tmp/afh03-monocular/qa-report.json。
- 未执行检查、阻塞与所需硬件：documents/render_docx.py 因缺少 soffice.exe 失败，已用 Word COM 导出及 pypdfium2 完成替代渲染检查。没有安装 DA3、下载权重、运行 GPU/NPU 或测试相机；没有重新执行 RTL 回归、布局布线或上板。硬件吞吐、模型效果和测量精度均为待验证项。
- 修改文件与设计理由：新增 Word 保留前版编号技术段落文风。主线为球轮廓几何测距，DA3 Metric Large 作为 PC 对照。FPGA 用低分辨率帧差和网格统计替代复杂背景、形态学和连通域；保留原始测量 ROI。NPU 以一个球/手/拍模型低频识别，CPU 高频轮廓、跟踪及事件状态机。120 fps 为首版目标，240 fps 为验证后升级；特别指出现有单像素 100 MHz 核不足以支撑 157.3 Mpixel/s，必须重新设计并行像素或验证更高频率。
- 下一步及验收条件：先按文末附录，用已标定相机在 1.3、1.4、1.5 米收集静止球与发球素材，比较球径法和 DA3 的厘米误差、抖动、失败率；先通过几何与事件实验，再部署 FPGA/NPU。第 13 节的误差和覆盖率仅为建议验证门槛，不替换已冻结的项目验收契约。接口实现前由相关模块负责人评审。

资料核验包括 SC130GS 官方产品 flyer、本地安路指南物理第 9～11 页、OpenCV calib3d、Rockchip Model Zoo、DA3 官方 README/API/输入缩放源码及模型卡。DA3 的米制换算须使用实际模型输入尺度对应的像素焦距。文末参考资料含可点击链接。

前版《技术路线_AFH03与双NV1100M详细方案.docx》保留 SHA256：cccbcf78bd4dc1f00d574e96893df6ab0227ea8636772f488a8b292fe5907b39。
新版 SHA256：4d2b12bd9696b6a85a08e1ca75c121a57ae3dbfe0278b8a387a8d8168b640a5b。

接手者先阅读 AGENTS.md、当前规划与本交接。不要把本次方案编写当作新增算法已经实现，也不要覆盖用户其他 Word 或现有工作。
