# TD 批处理验证记录

日期：2026-09-20。结论：可以不使用 computer use，通过 CMD → PowerShell → TD Tcl 完成 PH1A180SFG676 最小设计的综合、布局布线和报告生成。

| 项目 | 实测结果 |
|---|---|
| 安装目录 | C:\Anlogic\TD_Release_2026.1_SP2.200.067 |
| TD 日志版本 | Release_2026.1_SP2，Build 6.2.2.200067 |
| Tcl | 8.6.15，import_device 命令可用 |
| 器件 | ph1_180.db / PH1A180SFG676，默认 speed 2 |
| 输入 | 24 位计数器；50MHz 测试时钟；不含真实板卡引脚约束 |
| 最终调用 | tools\run_td_smoke.cmd |
| 退出码 | 0；SUCCESS.txt 与 TD_SMOKE_PASS 均存在 |
| 产物 | gate.db 244438 B；route.db 266088 B；route_timing.rpt 162221 B；资源报告均非空 |
| 测试资源 | 25 LUT6、25 寄存器、3 IO；无 DDR/MIPI/NPU 模块 |
| 测试时序 | SWNS 17.470ns，HWNS 0.316ns；STA coverage 82.25%，不是完整板级时序签核 |
| 反向检查 | 传入不存在的 TD 安装路径时，CMD 返回 1，没有误报成功 |

最终产物位于 `tmp/td-smoke-20260920-223216-7267ec4a/`；完整 console.log 和 route_timing.rpt 可在本机查看，tmp 不进入 Git。route.db SHA256：`D2FBB5EC2E0EC6F0D75B31954AE004CC9E148B277BBF80CAC14B78805FBBF777`。

发现并处理的调用问题：

1. TD 启动器收到带空格的 Tcl 完整路径时报 source 参数错误，进程仍可能退出 0。现在进入工作目录，传相对脚本名，并同时检查标记与输出文件。
2. 初次探测成功执行到 bitgen，但 TD 报 BIT-8123：IO 未分配实际引脚。失败记录在 `tmp/td-smoke-01/`。最终脚本停在 route/report，不解除该保护、不生成可误烧录的文件。
3. 此机器从 CMD 启动的 Windows PowerShell 无法解析 Get-FileHash；包装脚本改用 .NET SHA256，重新实跑成功。

复现说明见 `fpga/smoke/td_batch/README.md`。调用依据为安装自带 SWUG105_TCL_Command_User_Guide.pdf 第 2.2.1.2 节与第 3.2.2 节。

未验证项：真实引脚与时钟、RTL 行为正确性、厂家 DDR/MIPI IP 许可、bitstream 成功生成、JTAG 下载、相机采集和实机运行。后续拿到板卡约束后再扩展 bitgen；此次没有修改安装目录、许可或系统环境变量。
