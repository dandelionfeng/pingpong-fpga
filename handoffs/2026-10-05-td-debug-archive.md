# TD 调试工程与旧代码归档交接

- 任务编号/负责人：2026-10-05 TD 调试归档，Codex 按蒲公英的归档要求执行；GitHub 同步与合并沿用已授权的仓库整理范围，最终审批人为蒲公英。
- 基准提交号/工作分支：`3bc38b63d94498e76e4d456971729941c72139dd` / `codex/archive-td-debug-20261005`，开始时工作区干净。
- 当前目标与不包含的范围：把旧实验源码、TD runner、testbench、报告和本地生成工程集中归档，更新当前开发入口。最新技术路线、个人分工、Word/PDF、厂商资料和历史交接保留原样；算法、协议与 FPGA 端口保持原版本。
- 允许修改的文件：旧 `fpga/afh03_image/`、`fpga/rtl/afh03_image/`、`fpga/sim/afh03_image/`、`fpga/smoke/td_batch/` 与 4 个 runner、4 个报告的路径；`archive/fpga-debug/`、本机 `archive/local-debug/`；`.gitignore`、README/FPGA/方案/报告/归档/交接索引、AGENTS.md、AI agent 指南、PC 执行清单、本次核查报告和交接。
- 输入输出/依赖的接口版本：旧 PH1A180 工具测试、PH1A90 基础图像实验按原历史范围保存；内部 `afh03-image-v0.1` 原文进入归档，新运动 Mask 接口仍按现行草案管理。现行技术参数与三人职责保持原版本。
- 环境与复现命令：Windows PowerShell；Python `C:\Users\20743\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。本次临时清点/搬迁/核查脚本在被忽略的 `tmp/td-debug-archive-20261005/archive_task.py`；调用 `inventory` 保存基线，`apply` 校验绝对路径后移动，`verify --staged` 核对归档字节、Git 暂存字节、时间戳、原路径移除、未修改文件和现行链接。常规入口为 `python tools/check_repo.py --staged`、`python -m unittest discover -s tests -v`、`git diff --cached --check`。
- 已执行检查及真实结果：24 个已入库旧文件和 366 个本地生成文件搬迁前后 SHA-256、大小与本机修改时间逐项相同；24 个归档文件的暂存字节也一致。151 个范围外的已入库文件保持原样，其中最新技术路线与分工 11 个文件保持原字节；188 个现行本地链接可解析。本地归档全部被 Git 忽略，暂存区中无生成工程。仓库基础检查为 190 个文件、0 个问题，5 项单元测试通过，`git diff --cached --check` 通过。详细核查见[报告](../reports/TD调试归档核查_20261005.json)，原文件路径、字节数和哈希见[源码清单](../archive/fpga-debug/v2026-10-05_td_experiments/files-sha256.json)及[本地摘要](../archive/fpga-debug/v2026-10-05_td_experiments/local-projects-summary.json)。
- 未执行检查、阻塞与所需硬件：本次未重跑旧图像仿真、TD 综合/布局布线、项目重新打开或 FPGA 上板；现行七级 RTL、完整 PC 闭环与正式硬件部署仍待后续任务实施。旧生成工程的路径信息保持原样，迁移后打开状态未验证。
- 修改文件与设计理由：源码和 runner 全部从现行目录移到版本归档，避免后续任务误用；生成工程保留在被忽略的本地目录。新 `fpga/README.md` 与索引说明旧路径映射及当前待实现状态，现行构建与测试显式从任务目录取输入。
- 下一步及验收条件：下一位先读 [FPGA 说明](../fpga/README.md)、[现行方案](../plans/current/README.md)、对应个人说明第二部分和 [AI agent 指南](../docs/AI_agent协作指南.md)，在新任务分支实现当前模块。需要复用旧模块时，按[调试归档说明](../archive/fpga-debug/v2026-10-05_td_experiments/README.md)选取并重新验证，历史证据继续按原范围读取。
