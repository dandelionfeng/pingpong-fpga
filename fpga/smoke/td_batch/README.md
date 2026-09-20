# TD 命令行冒烟测试

目的：不用界面自动化，验证本机 TD 能加载 PH1A180SFG676，读取 Verilog/SDC，执行综合、布局布线并生成报告。电路为 24 位计数器，不属于产品功能实现。

在仓库根目录运行：

```powershell
.\tools\run_td_smoke.cmd
```

指定其他安装目录：

```powershell
.\tools\run_td_smoke.cmd -TdRoot "C:\Anlogic\TD_Release_2026.1_SP2.200.067"
```

每次运行创建独立的 `tmp/td-smoke-时间-随机编号/`，保存输入副本、console.log、综合/布线数据库、资源报告、route_timing.rpt 和 SUCCESS.txt。不会清理或覆盖已有运行。失败抛出错误；不能只看 TD 退出码，需要同时检查成功标记与完整产物。

入口来自安装自带 SWUG105_TCL_Command_User_Guide.pdf 第 2.2.1.2 节：`td_commands_prompt.exe demo.tcl`；命令顺序参考第 3.2.2 节。Tcl 用 catch 捕获失败，并记录失败阶段。

实测 TD 启动器对包含空格的 Tcl 完整路径存在解析问题。因此脚本先切换到输出目录，只传 `run.tcl`；仓库路径本身包含空格仍可正常工作。

验证边界：器件默认 speed 2，50MHz 为合成测试约束；未指定真实板卡引脚、IO 延迟及复位时序，不能据此认定板卡时序达标。测试不运行 RTL 功能仿真，不连接 JTAG，不生成或烧录 bitstream。初次探测调用 bitgen 时，TD 因未约束 IO 报 BIT-8123，已保留失败日志；不要打开 unconstr_io 绕过该保护。

后续正式工程需核对实际器件速度等级、板卡原理图、时钟与 ADC/SDC 约束后，另行扩展 bitgen 步骤。厂商 IP 所需许可需随具体 IP 单独验证，此次仅证明基本流程许可可用。
