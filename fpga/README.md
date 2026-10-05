# 当前 FPGA 开发入口

正式目标沿用 [AFH03 USB 同步双目方案](../plans/current/README.md)：PH1A90SEG324 接收左右眼搜索图，运行七级运动前端并返回 1 bit Mask。A 负责前三级和系统接口，B 负责后四级和打包，职责细节按最新个人文件执行。

截至 2026-10-05，现行运动 RTL 尚待实现。`rtl/`、`constraints/`、`sim/` 留作新任务的源码、约束和测试入口；已有空目录只表示预留位置。新任务明确列出模块与测试文件，构建和测试发现从本任务目录取输入。

旧 TD 工具链计数器测试、基础灰度/去噪/亮度/ROI 内核、testbench、runner 和报告已移入[调试归档](../archive/fpga-debug/v2026-10-05_td_experiments/README.md)，本地生成工程移入被 Git 忽略的 `archive/local-debug/`。归档保留历史实现与证据，供指定模块参考；当前开发入口已移除旧实验源码和脚本。

当前技术路线 Markdown、Word 和 PDF 中提到的原 `fpga/rtl/afh03_image/`，可按[原路径与 SHA-256 清单](../archive/fpga-debug/v2026-10-05_td_experiments/files-sha256.json)定位。复用时把选定模块复制到新任务目录，注明来源、接口差异，并为现行双路运动流水线重新编写验证。内部图像内核接口和新运动 Mask 接口分别管理。

先读 [AGENTS.md](../AGENTS.md)、[接口草案](../项目规划/接口与验收契约.md)、对应个人说明第二部分及[最新交接](../handoffs/README.md)。后续提交记录实际 PC/RTL/综合/实机检查，生成工程、厂商工具与授权资料继续留在被忽略的本地目录。
