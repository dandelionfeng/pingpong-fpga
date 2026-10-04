# 任务交接

- 任务编号/负责人：github-current-sync-20261004 / Codex。
- 基准提交号/工作分支：`c638158281dff65ec9a7750ac85ae4b4d5f9dfcf`；`codex/sync-current-plan-archive-20261004`。开始时 `origin/main` 为 `cb7d75024a7baf9f3deed55e97b0c176564f92bd`，是当前分支祖先；本轮整合已有未合并历史与最新未提交方案，不丢弃既有修改与删除。
- 当前目标与不包含的范围：同步最新技术路线和三人职责文件到 GitHub；归档旧版本，整理 README 及引用入口，更新 GitHub 使用指南、AI agent 指南和仓库描述。本轮不改算法、RTL 行为、模型输入、协议字段或判罚阈值，不重写最新 Word/PDF。
- 允许修改的文件：当前入口、协作指南及项目规则、相机选型与清单、基础图像模块说明、归档与清单、报告与交接；纳入之前已授权的最新方案/分工文件和文档核查记录。旧 FPGA 直采/UDP/ROI 和 RK3566 空目录占位归档；保留已有 RTL、脚本和历史测试报告。
- 输入输出/依赖的接口版本：以 2026-10-04 PC 先行版、72°/3.6 mm 双 OV9281、AFH03 RK3576J/PH1A90SEG324、固定 YUY2 60fps 和 Mask 主路径为准。新传输语义仍是负责人评审草案，既有 `afh03-image-v0.1` 内部端口保持不变。
- 环境与复现命令：Windows PowerShell、Git、便携 GitHub CLI 与捆绑 Python。基础命令为 `python tools/check_repo.py --staged`、`python tools/check_repo.py`、`python -m unittest discover -s tests -v`、`git diff --cached --check`；归档和原文件检查记录见报告与清单。
- 已执行检查及真实结果：26 份历史文件保存原始字节并记录 SHA-256；11 份最新路线/分工文件与本轮开始时的哈希保持一致。27 份现行 Markdown 的 158 个本地链接通过；184 个候选文件基础检查无问题；已有 5 项卫生检查测试通过，`git diff --check` 与 `git diff --cached --check` 无空白错误。暂存区和工作区各检查 184 个跟踪文件，均为 0 问题。发布内容提交的 GitHub 检查已通过，核查报告为 `reports/仓库同步与归档核查_20261004.json`。
- 未执行检查、阻塞与所需硬件：本轮是仓库整理与文档同步，没有运行算法、现行七级运动 RTL、模型训练、RKNN Runtime 或板卡测试。原 100° 商详不能代替所购 72° SKU 证据；当前固件模式、定量同步与实物表现继续登记。
- 修改文件与设计理由：当前入口统一到 `plans/current/` 与最新个人文件；旧指南的 FSIN/UDP/RK3566 分工改为当前 A/B/C。新增 AI agent 指南及原交接包入口，说明自主实现、真实验证与授权并行边界。最新 Word/PDF 原样上传；归档保存旧版本而不改旧内容，历史交接与报告保留日期和适用范围。
- 下一步及交付材料：从 `README.md`、`plans/current/README.md`、`docs/AI_agent协作指南.md` 和对应个人文件第二部分领取实现任务；用末尾提示词开展自主实现。2026-10-04 实际读取 GitHub main 保护：需要 1 个批准评审、`repository-checks` 通过及最新 main，管理员同样受约束，禁止强推/删除；与 `CONTRIBUTING.md` 的队友评审约定一致。整合 [PR #9](https://github.com/fengfengkang/pingpong-fpga/pull/9) 已创建为非草稿，目标 main；最新文件已上传，合并仍待队友批准。

仓库描述已通过 API 修改并重新读取确认，保持 Private 和默认分支 main：2026 FPGA 自主命题：AFH03（RK3576J + PH1A90SEG324）与 USB 同步双 OV9281 的乒乓球发球三维测量；FPGA 运动前端、CPU 球心与轨迹、NPU 三类识别，先完成 PC 算法闭环再部署。

本轮归档与入口核查在本机由 `tmp/github-sync-20261004/verify.py` 执行；临时备份和整理脚本留在被忽略的 tmp，GitHub 保存报告、清单和现行文档。实际基础验证命令如下：

```powershell
& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -m unittest discover -s tests -v
# 5 tests，OK。
git diff --check
# 退出码 0；现有 Markdown 的 CRLF/LF 规范化提示不改变正文。
& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' tools/check_repo.py --staged
& 'C:/Users/20743/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' tools/check_repo.py
# 均退出码 0；Checked 184 tracked files; 0 problem(s)。
git diff --cached --check
# 退出码 0。
```

接手 agent 先阅读 AGENTS.md 与最新规划，不依赖上一段聊天隐含的信息。

## GitHub 发布结果

内容提交 `fe63a7a36abdf7775be1abbf3f8c8a0739d50cd1` 已推送到 `codex/sync-current-plan-archive-20261004`，远端 ref 与本地 SHA 一致。整合 [PR #9](https://github.com/fengfengkang/pingpong-fpga/pull/9) 为 OPEN、非草稿、可无冲突合并；`repository-checks` 已成功，记录见[Actions](https://github.com/fengfengkang/pingpong-fpga/actions/runs/37194215752)。本段和报告通过随后文档补记提交发布，最新检查状态以 PR 为准。

当前 `reviewDecision=REVIEW_REQUIRED`、`mergeStateStatus=BLOCKED`，尚未合入 main。服务器要求另一位有写权限的队友在 GitHub 批准；没有尝试绕过、降低保护或自我审批。队友审批后先重新核对最新 SHA、检查和评审状态，再通过 Squash and merge 合入。当前方案与归档均可在 PR 分支直接读取。

之前 #1、#5、#6、#7、#8 的已有提交均包含在整合分支历史中。旧 PR 及远端分支保留追溯，本轮未关闭旧 PR、删除分支或改写共享历史。后续从最新已评审 main 起任务；审批前如需使用当前成果，明确以本整合分支为依赖。
