# 任务交接

- 任务编号/负责人：2026-09-28 工作区整合、历史版本归档与 GitHub 同步 / Codex。
- 基准提交号/工作分支：`8f94786` / `codex/workspace-archive-20260928`。
- 当前目标与不包含的范围：保留 AFH03 上相机直入 FPGA 与直入 RK3576J 两条单目方案；按日期和平台归档旧技术路线与采购说明；整理资料入口并把可共享内容同步 GitHub。此任务不修改两份现行 Word/PDF 的技术内容，不冻结新协议或声称硬件已打通。
- 允许修改的文件：方案及历史资料的路径，`README.md`、`AGENTS.md`、`项目规划/项目实施规划.md`、`项目规划/接口与验收契约.md`、`docs/实施前待确认项.md`、`plans/current/README.md`、`archive/README.md`、`data/manifests/afh03-vendor-package.md`、`fpga/afh03_image/README.md`、本交接文档；原有未入库的 FPGA 源码、报告、分工文档和交接记录随工作区一同提交，内容不作技术改写。
- 输入输出/依赖的接口版本：两条现行路线的接口待评审。旧 H10/RK3566 UDP v0.4 契约迁入历史版本；原路径保留说明入口。RK3576J 直采分工仍指向其现有 Word 方案。
- 环境与复现命令：Windows PowerShell、Git、bundled Python。归档校验见 `archive/moved-files-sha256.csv`；本地厂商资料见 `vendor/HW_MLK_AFH03_20250402_AFC03_20250402_RK+AL/`，由 `.gitignore` 排除。
- 已执行检查及真实结果：23 个 Word/PDF/Markdown 文件在搬迁前、搬迁后及 Git 暂存区中的 SHA-256 完全相同；厂商目录本地迁移前后均为 118 个文件、162,033,659 字节。新入口页的 44 个本地链接均可解析；两份当前 DOCX 和一份 PDF 均可重新打开，PDF 为 11 页。`python -m unittest discover -s tests -v` 通过 5 项；`python tools/run_image_pipeline_tests.py` 通过 3 组随机停顿种子与灰度模块测试，每组匹配 126381 个输出节拍。`python tools/check_repo.py --staged` 检查 119 个暂存文件，0 个问题；`git diff --cached --check` 通过。尚未执行硬件验证。
- 未执行检查、阻塞与所需硬件：尚未做真实相机接线、RK CSI 采集、FPGA FMC 采集、PCIe DMA、模型推理和整链路性能测试；需要实物、模组 mode 表及厂商例程。厂商资料本体按协作规则留在本地，不进入 GitHub。
- 修改文件与设计理由：当前两条路线集中到 `plans/current/`，旧 H10、DR1M90G、AFH03 双目方案放到 `archive/routes/`，旧采购资料放到 `archive/procurement/`；README 与原有必读路径提供清楚入口。历史文档保持原内容及校验和，避免将旧报价和旧性能目标用作现行结论。
- 下一步及验收条件：A/B/C 阅读 `plans/current/README.md` 后评审两条路线的接线、驱动和接口；选定要实施的路线并冻结黄金数据样例。后续 PR 合入 main 前由负责人审查历史资料范围与现行方案入口。
