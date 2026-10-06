# 最新 PR 审查与 A/B 材料交接

- 任务编号/负责人：2026-10-06 / A（蒲公英的 Codex）。
- 基准提交号/工作分支：main `d6cf530`；A 原交付 `3be59aa`、开发入口修复 `641df0a`；分支 `codex/a-usb-fpga-pipeline-20261005`。保留其他人的修改，B PR 用独立 worktree 固定 head 评审。
- 当前目标：评审最新 B PR #12～#14，并将本机 A 共用核心、源码、运行包、接口与黄金输入实际发布到团队私人仓库。没有相机/AFH03/受限 SDK，不做整机验收声明。
- 允许修改文件：A 已实现目录及此次交接/审查报告、人工输入打包脚本、审查复现 TB、发布清单和索引。B/C 算法与原始规划未改。
- 输入输出/依赖：`a-motion-v1-draft`、B2/B3 当前草案；保留 pair/eye/sample/reference/version。Mask LSB0 和 ROI 差异均待技术复核，硬件协议仍待蒲公英审批。
- 环境与复现命令：见 [PR 审查报告](../reports/PR审查_20261006.md) 与 [B 接入 A 材料](../docs/B接入A交付材料.md)。OpenCV C++ 固定 4.13.0、Qt 6.8.3、Icarus 12.0。
- 已执行检查：B2 42 个检查和 54/54 合成场景通过；B3 在仅补目录的临时副本 8/8 CTest 通过。B1 原例通过，但启动同拍与短帧复现失败；B2/B3 正式路径和 B3 构建脚本阻塞。A 新人工包 CPU/mock 一致，176 图/48,971,776 像素核对通过。
- 上传前基础检查：`python tools/check_repo.py --staged` 检查 252 个 tracked 文件，0 问题；`python -m unittest discover -s tests -v` 的 5 项通过；本机 `ctest --test-dir build/a_pipeline_windows --output-on-failure` 的核心检查通过。
- 未执行/阻塞：B3 原验证入口不完整，整套 v2 评分未重跑；B/C 真正的 A 适配库、C 独立评分、真实双目标定与实际板卡仍待接入。B 公布的开发回归不替代独立评分。
- 修改理由：队友在 GitHub 上原先拿不到本机未推送 A 核心；补充可下载源代码、程序和同帧输入/黄金输出，提供明确接入和复现入口。
- 发布：<https://github.com/fengfengkang/pingpong-fpga/releases/tag/a-pipeline-pc-20261006>；访问权限保持 private；附件哈希与版本在 [发布清单附件](https://github.com/fengfengkang/pingpong-fpga/releases/download/a-pipeline-pc-20261006/a-pipeline-release-20261006.json) 及 `data/manifests/` 仓库副本中。GitHub 发布结果另由本次操作记录确认。
- 下一步/验收：B 修复三项 PR 的具体阻塞，从干净 checkout 复现入口；A/B 技术复核后实现 `pipeline_b_module`，C 接入实际模型，重跑共同 PC 闭环。设备到货后补 USB、PCIe、DDR3L 和整机日志。
- 审批依据：蒲公英本轮明确授权“没问题就通过，有问题提出来；需要提供的东西也一并上传”。对存在已复现问题的 B PR 请求修改；上传使用私人仓库 PR/Release，符合 CONTRIBUTING.md。
