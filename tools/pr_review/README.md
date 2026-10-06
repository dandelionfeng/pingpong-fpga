# 固定 PR 的失败复现

本目录用于复现 2026-10-06 的 GitHub 审查问题，报告见 `reports/PR审查_20261006.md`。B 的实现未在评审中修改。

`b_morphology_protocol_tb.sv` 用 Icarus 12.0 编译，与 #12 head `e4212d6b34be8854041d7b2a28cf5938568fea52` 的 `morphology_mask_chain.sv` 一起运行：

```powershell
& '<Icarus12>/iverilog.exe' -g2012 -s tb_protocol_review -o review.vvp fpga/rtl/morphology/morphology_mask_chain.sv '<A源码>/tools/pr_review/b_morphology_protocol_tb.sv'
& '<Icarus12>/vvp.exe' review.vvp
```

当前版本预期失败：启动同拍六行 `got=07 expected=0f`；短帧六行 `byte=ff`；最后 `REVIEW_PROTOCOL_FAILURES=12` 和退出 1。短帧必须由正式接口拒收；该文件是当前 head 的诊断复现，修复后应按约定错误通道补回归，不能通过把短帧补零来掩盖错误。

原作者 8×6 背压例子通过。本复现不声称 640×360、行缓存、双眼集成、TD 或实物验证通过。
