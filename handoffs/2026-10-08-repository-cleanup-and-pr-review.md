# 仓库精简与修订PR复核交接

- 任务编号/负责人：2026-10-08 / 蒲公英的Codex。
- 基准提交/工作分支：`3de63bdd1d6d7b92d0cb473c34b33e6b87afe26e` / `codex/repo-cleanup-20261008`；基准已包含本次正常Squash合入的#15/#16/#17。
- 目标：回答旧/新PR状态、复核修订版、把历史资料保存在本地并精简GitHub当前文件树、说明PC阶段交付变化。没有改B算法或共同接口/阈值，没有实现完整B/C适配或硬件功能。
- 允许修改：历史文件删除与本地清单、现行索引及状态/复核/交接说明、轻量架构图源和维护脚本。原工作区H10/JTAG、Word、TD脚本和板卡资料修改保留在原位置，未夹带提交。
- 接口/版本：`a-motion-v1-draft`、`b-measure-v2-draft`；B的`frame_error`和启动拍语义按其修复交接。来源帧、眼别、时间、reference和版本继续贯穿；协议仍为草案。
- PR实际结果：旧#12/#13/#14已关闭未合并；#15合入ce1b873、#16合入45be2dc、#17合入3de63bd；#18固定head2aa69f7实际干净入口缺依赖，重复BPart2/空模板/清单冲突已请求修改。具体命令与范围见[复核报告](../reports/PR审查_20261008.md)。
- 本地备份：`C:/FPGA competition-backups/20261008-repo-cleanup`，保存159份原始工作区及Git字节；141项删除、1项清单重定位、17个索引旧版留存，全部核对SHA-256。完整Git bundle已verify；本机原archive/local-debug、vendor、素材、工具和运行包未删除。
- 环境/复现：Windows、MSVC19.44、OpenCV C++4.13、Icarus12；Python版本见复核报告。维护脚本`python tools/maintenance/backup_history.py --backup-root <仓库外本地目录> --apply`仅适用于本任务分支和清理前基准；日后恢复按[本地定位页](../archive/README.md)逐项复制并核对，避免覆盖现行代码。
- 已执行检查：A核心CTest；B球心3组42检查及54场景；B小尺寸RTL协议仿真；新head GitHub检查后合并。整理的备份/活动文件/Word字节、链接、暂存hygiene及5个仓库unittest结果在[机器记录](../reports/仓库整理与PR复核_20261008.json)。
- 未执行：完整A/B/C共同程序、实际C模型/独立冻结评分、B第三部分整套v2、640×360七级联接、TD5.6.2重新综合、Linux/ARM新增回归、真实USB/DMA/DDR3L/PCIe/RK/NPU/HDMI与整机。清理不等于这些验收通过。
- 设计理由：首页指向当前使用入口；archive只留本地定位与共享清单；现行路线/分工/原算法报告保留字节，旧编辑过程转为本地；B清单归入专用目录，避免根目录混杂。架构图仅共享SVG/结构源，PNG本地导出。
- 下一步：B从最新main更新#18并去除旧副本，处理冲突后运行正式v2并补PR正文；A/B封装真实`pipeline_b_module`，C提供实际`pipeline_c_module`与独立评分，完成共用核心/Qt闭环。设备验收分别留证据。
- 审批依据：蒲公英此前“没问题就通过，有问题提出来”及本轮“整理GitHub仓库，旧文件本地保留”；按CONTRIBUTING正常分支/PR、检查和Squash流程执行，不强推或绕过必需检查。

当前入口：[PC交付状态](../docs/当前PC阶段交付状态.md)、[架构图](../docs/architecture/README.md)、[备份清单](../data/manifests/local-history-20261008.json)。
