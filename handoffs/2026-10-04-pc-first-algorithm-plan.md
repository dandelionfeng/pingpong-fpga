# 任务交接

- 任务编号/负责人：2026-10-04 无硬件 PC 算法闭环技术方案与三人分工；Codex 文档修订。
- 基准提交号/工作分支：`c638158281dff65ec9a7750ac85ae4b4d5f9dfcf`；`codex/pc-first-algorithm-plan-20261004`。从已有带未提交修改的分支新建，未提交或推送。已有 `rk3566/` 五处 `.gitkeep` 删除及其他先前材料保持原状态。
- 当前目标与不包含的范围：评估引用对话、更新当前路线及总表/A/B/C 工作表，形成无实物执行和迁移验收清单。本轮没有开发图像核心、模型或 RTL，也没有训练、仿真、目标综合或上板。
- 允许修改的文件：当前路线 `.md/.docx/.pdf`；现行总分工及三份个人说明 `.md/.docx`；README、当前方案索引、实施规划/契约入口、实施前待确认项；新 `docs/PC算法闭环与部署验收.md`、本交接和文档核查报告。快照、构建、渲染材料在 `tmp/usb-stereo-pcfirst-20261004/`。
- 输入输出/依赖的接口版本：以工作区 2026-10-02 72°镜头和Mask路线 Word 为基础，引用对话附件与该文件 SHA256 一致。现行版本为 `2026-10-04 无硬件 PC 算法闭环版`；硬件路线和模型输入不变，文件/运动/检测后端及错误/来源字段为新增逻辑语义草案。2×2取整、首帧/reference_id、位序等尚待10月5日A/B/C评审，未冻结二进制布局和判罚阈值。
- 环境与复现命令：使用 `C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`（下记 `$taskPython`），以及本机 Microsoft Word COM。实际运行的作者/检查命令如下；重建会覆盖本轮五份现行文件，执行前先保留之后新增的人工编辑。

```powershell
$taskPython = 'C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $taskPython 'tmp\usb-stereo-pcfirst-20261004\author.py'
& '.\tmp\usb-stereo-pcfirst-20261004\render_documents.ps1'
& $taskPython 'tmp\usb-stereo-pcfirst-20261004\verify_and_render.py'
git diff --check
```

- 已执行检查及真实结果：五份Word分别12/3/4/4/4页，共27页；Word COM导出PDF后以pypdfium2逐页渲染并人工检查，修复表头单独留在页末的问题及附录前大空白。五份Markdown与Word正文/表格归一化一致。A/B/C各有九项任务和相同六阶段日期。路线原批注相关ZIP内容、原锚点段落保持，Word确认锚点“Linux”“按 60 fps 组织”仍为已解决。现行Markdown链接均存在，旧镜头/两模式/FPGA求球心的入口描述已同步。最终报告为 `reports/PC算法闭环方案文档核查_20261004.json`。
- 未执行检查、阻塞与所需硬件：文档技能附带 `render_docx.py` 实际运行提示缺少LibreOffice `soffice.exe`，已用现有Word COM完成真实渲染，无安装软件。算法验收P1～P9及模型训练/导出未运行；工具链可用性、数据许可与完整标签尚由执行人核实。相机同步/实际模式、最终标定、灰度域模型、AFH03 DDR3L/PCIe、RKNN/RGA/性能等等待实物。
- 修改文件与设计理由：2.1～2.8各补PC输入/检验/迁移说明，2.9改为先PC的剩余日期，附录C明确验收边界；总表与三份个人表从同一内容源生成。A新增整数前端/集成，B集中RTL后四级和测量，C新增事件真值/独立评分以平衡任务。详细清单规定truth隔离、独立双目投影、replay/model分列、异步故障和到货D排期。PDF同步最终Word，旧独立延期方案保留历史用途。
- 下一步及验收条件：A先建文件入口/格式/缓存并交B/C；B给像素审查和球心/几何结构，启动后四级RTL；C交数据/三类补标、事件观测和独立测试包。5日输入与语义、8日独立模块、10日全流程、12日PC总验收是待执行目标。任何通过结论都附实际命令/输入哈希/日志；模型模式未通过时不以检测框回放代替。相机/AFH03到货后逐层替换并同图对照，再做真实静态、动态与稳定性验收。

接手人先读 AGENTS.md 与当前方案，按 `docs/PC算法闭环与部署验收.md` 推进。
