# 第一部分 RTL 协议修复提交说明

本包修复 A 评审指出的两个功能问题：启动同拍首像素丢失，以及提前 `in_last` 时把短帧当完整帧处理。新增 `frame_error` 错误脉冲，并补充 Icarus 12.0 回归。

建议分支：`codex/b-motion-mask-protocol-fix`

建议提交信息：

```text
fix(fpga): reject short frames and correct mask input handshake
```

建议 PR 标题：

```text
fix(fpga): harden morphology mask frame protocol
```

合入前运行：

```powershell
& '.\fpga\sim\morphology\run_morphology.ps1'
```

本包不包含 build 目录、`.vvp`、`.vcd`、生成工程或二进制文件。正式 TD 综合、时序、PCIe、双眼实际输入和上板验证仍需后续执行。
