# 贡献流程

每个任务明确负责人、目录、输入输出和验收条件。任务分支从最新 origin/main 创建，命名如 feat/a-fsin、fix/b-udp-length、docs/c-calibration。

提交前检查暂存差异，运行 `python tools/check_repo.py --staged` 和任务相关验证。提交信息写清目的，例如 `feat(fpga): add FSIN pulse generator`。

PR 必须说明改动目的、接口影响、验证证据及未验证内容；至少一名其他队友阅读差异后批准。影响 FPGA 与 RK3566 的协议改动需双方确认。CI 绿色仅表示仓库基础检查通过。

使用 Squash and merge 合入 main。不要在共用分支 rebase 或 force push。冲突由双方核对后解决，不直接接受整份 ours/theirs。

每次稳定上板演示记录源码提交号、工具版本、板卡与相机配置、权重校验和和复现步骤。具体操作见 docs/协作使用指南.md。
