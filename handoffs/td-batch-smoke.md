# 任务交接：TD 批处理调用验证

- 任务/负责人：蒲公英要求测试 C:\Anlogic 的 TD 脚本调用；Codex。
- 基准提交/分支：87356c0；chore/td-batch-smoke。
- 修改范围：fpga/smoke/td_batch、tools/run_td_smoke.ps1、tools/run_td_smoke.cmd、本交接与 reports/TD批处理验证.md。
- 输入：安装自带 SWUG105 Tcl 手册；PH1A180SFG676 数据库；独立计数器测试电路。
- 复现：仓库根目录执行 tools\run_td_smoke.cmd，检查新 tmp 目录日志、SUCCESS.txt 和非空报告。
- 实际验证：Tcl 入口及器件命令可用；综合、布局布线、时序报告完成。初次 bitgen 因无真实引脚约束被拦截；最终脚本只验收到 route 阶段。
- 未执行：RTL 行为仿真、真实板卡约束签核、烧录、相机/DDR/IP 联调。无 computer use 操作。
- 下一步：A 收集板卡 ADC/SDC、具体器件速度等级；在正式工程中复用批处理入口，按实际 IP 逐项验证。
