# 第三部分 v2 路径修正版交付记录

日期：2026-10-09。负责人：B / cluepiggie。

本目录只记录第三部分的验证入口、配置、工具版本和哈希，不覆盖仓库根目录已有的 `SOURCE_SHA256.json`。第三部分依赖主仓库中已合并的 `software/pc_pipeline/ball_measurement/`，必须与 `software/pc_pipeline/trajectory/` 同级；不再携带旧 `BPart2/` 外层副本。

本次依据 PR 审查意见修正了第三部分的可复现路径：CMake 直接检查同级第二部分目录，`run_validation_v2.ps1` 先调用已提交的构建入口，再从同一构建目录寻找 `trajectory_cli.exe`。完整 v2 入口已在本地通过：62 项第三部分检查、42 项第二部分回归、8/8 CTest、84/84 文件场景、棋盘留出 4/4 与 6/6。

证据来自 B 生成的合成双目、合成 Mask 和显式检测回放；C 真实模型、A 在线联调、真实相机标定、Linux/ARM、FPGA 综合和上板仍未验证。
