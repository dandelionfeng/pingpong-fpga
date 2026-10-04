# 任务交接

- 任务编号/负责人：AFH03-NEURAL-DEPTH-PLAN / Codex。
- 基准提交号/工作分支：8f94786 / codex/afh03-neural-depth-plan-20260927；未提交或推送，保留既有工作。
- 当前目标与不包含的范围：响应用户加入神经网络测距的要求，在当前单目 Word 基础上另建增强版。只改方案，不训练模型、不改 RTL 或冻结接口。
- 允许修改的文件：新增《技术路线_AFH03与SC130GS单目神经网络测距方案.docx》、本交接；临时制作文件位于 tmp/afh03-neural-depth/。
- 输入输出/依赖的接口版本：沿用最新本地 SC130GS Word 的 1.3～1.5 米机位及 240 fps RAW10 设置。发现该源文件已较前次交付修改，不使用前次生成脚本覆盖它。新增网络图像输入暂定 1×3×192×192、几何条件和深度输出均属接口草案，须相关负责人评审。原有契约和代码未动。
- 环境与复现命令：以 C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe 运行 `-X utf8 tmp/afh03-neural-depth/build.py`；PowerShell 执行 `& tmp/afh03-neural-depth/export.ps1`；同一 Python 执行 `-X utf8 tmp/afh03-neural-depth/qa.py`。build.py 读取当前前版并新增内容，复现需要下述哈希对应源文件。
- 已执行检查及真实结果：Word 共 8 页、93 段、无表格图片；第 8 节神经网络测距始于第 3 页。全部正文在 PDF 中存在，8 页 PNG 逐页检查通过；附录 DA3 代码语法检查通过，未执行。源文件哈希不变。render_docx.py 因缺 soffice.exe 失败，替代使用 Word COM 导出与 pypdfium2 渲染。
- 未执行检查、阻塞与所需硬件：专用网络未实现、未训练、未转换 RKNN，未运行任何 GPU/NPU 推理。0.2 GOP、100 万参数及 30～60 次/秒均为设计预算或目标；240 fps 逐帧 CPU 处理、DDR 带宽及 FPGA 并行时序仍需验证。
- 修改文件与设计理由：加入 MobileNetV2 式轻量卷积距离回归网络，输出归一化 log(Zc) 和可测量性；固定尺度 ROI 保留透视尺寸，真实球心距离标签监督。几何法与网络按独立验证误差选路，避免相关误差简单平均。增加常数 1.4 米基线、独立距离测试、相机到货后适配与量化评价。DA3 留在 PC 对照，不把其预测直接当真值。同步校正 240 fps RAW10 预算：DDR 展开帧写入约 629.1 MB/s、一个 ROI 加上下文与预览约 32.44 MB/s；FPGA 需 2 像素/拍 200 MHz 或 4 像素/拍 100 MHz 等待验证实现。
- 下一步及验收条件：先建立已知距离、固定尺度 ROI 数据集，在 PC 比较几何法、专用回归网络、DA3 和常数距离基线。独立场次及未见距离达标后进行 RKNN 量化，再测板端吞吐；不能直接将方案视为可用模型。

源文件 SHA256：20b15f6f07a740e954b5bf8dbf58c5f159aa59cb39bf1f38522f3baabda410cf。
输出 SHA256：f78bb09d5cfb5f186f9a8cc7d987c7fa25b1105689d0a0272e0e68c9729045dc。

接手者先读 AGENTS.md、最新规划和本交接。当前版本保留用户对前版的修改，不重新生成旧版覆盖原件。
