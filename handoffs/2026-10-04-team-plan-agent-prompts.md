# 任务交接

- 任务编号/负责人：team-plan-agent-prompts-20261004 / Codex。
- 基准提交号/工作分支：c638158281dff65ec9a7750ac85ae4b4d5f9dfcf；codex/team-plan-agent-prompts-20261004。从前一任务分支创建，保留所有已有未提交修改与删除。
- 当前目标与不包含的范围：将总分工改为前半段通俗职责和工具、后半段算法与实施方法；仅保留较宽的交付日期范围及交付对象。与三份个人文件统一函数、算法、软件和参数名称，并在个人文件末尾各追加一段可复制的 agent 提示词。本轮不启动其他 agent，不实现算法，不改总技术路线、全项目验收、接口契约及 README。
- 允许修改的文件：分工目录下 00 总分工及 01_A、02_B、03_C 的八份 Markdown/Word；本交接与本轮核查报告。任务专用临时目录保存备份、构建、检查及排版材料。
- 输入输出/依赖的接口版本：沿用当前 AFH03 RK3576J/PH1A90SEG324 与 USB 双 OV9281 路线。原个人文件正文保持原样；仅新增末尾提示词及对应排版。取整、边界、位序、描述符、模型输入、世界坐标及量化参数继续使用现有草案，本轮不改变协议和技术配置。
- 环境与复现命令：Windows PowerShell，捆绑 Python、python-docx、pypdfium2、pypdf；Microsoft Word 只读导出。任务工具入口为 `tmp/team-plan-agent-prompts-20261004/author.py`、`render_documents.ps1` 和 `verify_and_render.py`。完整重建运行默认入口；`--personal-only` 和 `-PersonalOnly` 可只重建、重渲染个人文件。
- 已执行检查及真实结果：四份文件各有两个主体部分，通俗部分没有具体算法名称，正文为段落且表格与编号列表均为零。总分工只保留 10 月 4～8 日、9～12 日、13～28 日三个交付窗口；交付部分没有成功条件。三份个人文件原正文一致保留，末尾各有一个角色专属提示词段落。58 项名称对应检查及关键参数比对一致，四组 Word/Markdown 内容一致；最终各三页，共十二页逐页视觉检查，无裁切、重叠、缺字及孤立标题。基线哈希比对仅八份授权文件发生修改，其余已有修改与删除保持原状。
- 未执行检查、阻塞与所需硬件：未运行算法、RTL 仿真、综合或实物检查，本轮是文档与提示词编辑。标准渲染器因缺少 LibreOffice soffice.exe 退出，已用 Word 导出和 pypdfium2 渲染完成检查。提示词用于之后的开发任务，尚未执行。
- 修改文件与设计理由：总分工用通俗段落说明 A 输入与整合、B 图像测量及三维事件、C 数据模型及独立复核，后半段使用个人文件已有的名称说明实现和交付。个人提示词引导 agent 定位当前文件、理解已有成果和接口、拆解并持续实现、复现与记录真实阻塞，同时保留协作评审约定。部署说明、交付材料与提示词在个人文件末页连贯排布。
- 下一步及交付材料：读总分工了解共用数据流和交付范围；读对应个人文件第二部分开展实现；末尾提示词可复制给承担该角色任务的 agent。交付为八份分工文件、核查报告和本交接。

实际执行命令及结果如下。

```powershell
& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'tmp/team-plan-agent-prompts-20261004/author.py'
# 退出码 0；生成四组 Word/Markdown，三段提示词分别为 531/545/576 字符。

& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'C:/Users/20743/.codex/plugins/cache/openai-primary-runtime/documents/26.909.12148/skills/documents/render_docx.py' 'C:/FPGA competition/项目规划/AFH03_USB同步双目方案一个月分工/00_三人分工与一个月实施安排.docx' --output_dir 'C:/FPGA competition/tmp/team-plan-agent-prompts-20261004/canonical-render' --emit_pdf
# 退出码 1；LibreOffice soffice.exe was not found on PATH。

& 'tmp/team-plan-agent-prompts-20261004/render_documents.ps1'
# 退出码 0；总分工及 A/B/C 各三页。

& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'tmp/team-plan-agent-prompts-20261004/author.py' --personal-only
& 'tmp/team-plan-agent-prompts-20261004/render_documents.ps1' -PersonalOnly
# 均退出码 0；调整个人文件末页布局后，只重新生成与导出 A/B/C。

& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'tmp/team-plan-agent-prompts-20261004/verify_and_render.py'
# 退出码 0；checks=passed，documents=4，canonical_name_checks=58，scope_changed=8，unrelated_changed=0。

git diff --check -- '项目规划/AFH03_USB同步双目方案一个月分工/00_三人分工与一个月实施安排.md' '项目规划/AFH03_USB同步双目方案一个月分工/01_A_USB采集与FPGA链路职责说明.md' '项目规划/AFH03_USB同步双目方案一个月分工/02_B_FPGA视觉与三维测量职责说明.md' '项目规划/AFH03_USB同步双目方案一个月分工/03_C_AI模型训练与部署职责说明.md'
# 退出码 0；仅 CRLF/LF 规范化提示，没有空白错误。
```

最终文件哈希复核与基线范围比对均通过：文档哈希对应已查看的版本，八份既有文件发生本轮修改，仅新增本交接和报告，共十二页视觉检查已记录。

核查报告为 `reports/总分工与Agent提示词文档核查_20261004.json`；中间 PDF、PNG 和备份不作为交付附件。

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖上一段聊天隐含的信息。
