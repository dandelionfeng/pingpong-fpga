# 任务交接

- 任务编号/负责人：personal-guides-prose-20261004 / Codex。
- 基准提交号/工作分支：c638158281dff65ec9a7750ac85ae4b4d5f9dfcf；codex/personal-guides-prose-20261004。分支从原工作分支创建，保留其已有未提交修改。
- 当前目标与不包含的范围：按用户要求重排三份个人分工，分别给出通俗职责和工具说明、具体实现方法及交付材料。去除任务编号、文件路径式说明、时间表和交付清单中的通过条件。总技术路线、总分工、接口契约和全项目验收文档不在本轮修改范围。
- 允许修改的文件：个人分工目录下 01_A、02_B、03_C 的六份 Markdown/Word；本交接及本轮文档核查报告。临时备份、生成和渲染工具位于任务专用临时目录。
- 输入输出/依赖的接口版本：沿用当前无硬件 PC 算法方案中的 AFH03 RK3576J/PH1A90SEG324、图像尺寸、七级运动前端、三人模块边界和模型输入配置。接口与位序仍按现有草案评审，本轮未调整协议、量化参数、坐标系或判罚阈值。
- 环境与复现命令：Windows PowerShell；捆绑 Python 配合 python-docx、pypdfium2、pypdf；Microsoft Word 只读导出。先运行任务目录中的 author.py，再运行 render_documents.ps1，最后运行 verify_and_render.py。以下记录为实际执行命令。
- 已执行检查及真实结果：三份文件各有且仅有两个主体部分；正文为段落，表格和编号列表均为零；通俗部分没有具体算法名称；没有任务编号、仓库路径和时间表；交付材料只写交付对象。三组 Word/Markdown 内容一致；三份最终 Word 各两页，共六页逐页检查，无裁切、重叠和缺字。工作区基线哈希比对仅发现本轮六份个人文件发生修改，其余已有修改与删除保持原状。
- 未执行检查、阻塞与所需硬件：未运行算法、RTL 仿真、综合或实物检查，因为本轮为文档重排。标准文档渲染器缺少 LibreOffice soffice.exe，已改用 Microsoft Word 导出和 pypdfium2 渲染完成排版检查；最终文档无需额外环境才能阅读。
- 修改文件与设计理由：三人仍按 A 输入/通信/整合、B FPGA 后半段/图像测量/三维事件、C 数据/模型/独立复核分工。第一部分解释工作目的和工具用途，第二部分保留实现细节、协作接口和所需交付材料。文件名保持原样，便于沿用已有入口；移除正文日期和页眉，只保留页码。
- 下一步及交付材料：直接阅读对应个人文件第一部分了解职责与工具，再阅读第二部分开展实现。技术依据和更完整的接口、算法测试仍查当前总方案与契约；本轮交付六份个人文件及核查报告。

实际执行命令与结果如下。

```powershell
& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'tmp/personal-guides-prose-20261004/author.py'
# 退出码 0；生成三组 Word/Markdown；表格数均为 0。

& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'C:/Users/20743/.codex/plugins/cache/openai-primary-runtime/documents/26.909.12148/skills/documents/render_docx.py' 'C:/FPGA competition/项目规划/AFH03_USB同步双目方案一个月分工/01_A_USB采集与FPGA链路职责说明.docx' --output_dir 'C:/FPGA competition/tmp/personal-guides-prose-20261004/canonical-render' --emit_pdf
# 退出码 1；LibreOffice soffice.exe was not found on PATH。

& 'tmp/personal-guides-prose-20261004/render_documents.ps1'
# 退出码 0；最终 A/B/C 各两页。首次渲染 A/B 三页，调整间距后重新渲染。

& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'tmp/personal-guides-prose-20261004/verify_and_render.py'
# 退出码 0；checks=passed，documents=3，scope_changed=6，unrelated_changed=0。
```

核查报告：`reports/个人分工段落版文档核查_20261004.json`。临时备份和渲染图不作为最终交付附件。

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖上一段聊天隐含的信息。
