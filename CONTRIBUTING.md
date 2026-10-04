# 贡献流程

每项任务明确负责人、允许修改的目录、输入输出与交付内容。技术依据从[当前方案索引](plans/current/README.md)进入；职责按最新 A/B/C 个人说明，agent 操作见[协作指南](docs/AI_agent协作指南.md)。

通常从最新已评审的 `origin/main` 建任务分支，Codex 使用 `codex/` 前缀，例如 `codex/a-file-input`、`codex/b-motion-mask`、`codex/c-pc-detector`。若任务依赖尚未合并的改动，保留这些成果，在交接和 PR 中写清基准提交、依赖 PR 与目标分支；已有未提交工作先妥善保存，不通过切分支丢弃。

提交前检查暂存差异，运行 `python tools/check_repo.py --staged`、`python -m unittest discover -s tests -v` 和任务相关验证。提交信息写清目的，例如 `feat(fpga): add motion mask packing`。基础检查不代替算法、RTL、模型或板卡测试。

PR 必须说明改动目的、接口影响、验证证据及未验证内容。所有审批由蒲公英最终确认，不额外要求另一位队友批准；蒲公英在任务对话或 PR 中明确授权同步/合并后，完成检查即可执行该授权。接口、模型和坐标变化整理兼容影响，相关模块负责人提供技术复核建议，最终交蒲公英审批。当前规划中的布局和阈值仍按草案管理。

检查通过且蒲公英已确认后使用 **Squash and merge** 合入 main。GitHub 保留 PR 和 `repository-checks` 要求，强制批准评审数为 0，避免同一仓库账号无法批准自己发起的 PR；最终审批依据记录在任务交接中。不要在共用分支 rebase 或 force push；冲突由双方核对后解决，不直接接受整份 ours/theirs。合并后同步 main，再从新基准领取下一项任务。

文档归档保留原始字节、来源与 SHA-256，修改 README 等现行入口；历史交接和测试报告保持原日期及适用范围。已有 Word/PDF 与 Markdown 的同步需在任务范围内明确授权。

每个稳定版本记录源码提交号、工具版本、输入包、配置和复现步骤。PC、RTL、综合、RKNN 转换与正式上板证据分开；实物版本补充板卡、相机、标定与模型哈希。大文件按[产物说明](artifacts/README.md)登记。具体 GitHub 操作见[使用指南](docs/协作使用指南.md)，交接用 [handoffs/TEMPLATE.md](handoffs/TEMPLATE.md)。
