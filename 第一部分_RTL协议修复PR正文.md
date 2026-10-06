## 目的与关联任务

修复 A 评审指出的 B 第一部分形态学 Mask 参考 RTL 两个协议问题：启动同拍 `frame_start/in_valid` 时首像素被错误丢弃，以及提前 `in_last` 的短帧被当作完整帧处理。依据 AFH03 USB 同步双目技术路线、B 第一部分职责说明和本 PR 行内审查意见。本轮仍是功能参考 RTL 修复，不是完整 FPGA 工程完成声明；不含行缓存替换、TD 综合、资源时序、DDR3L、PCIe 或真实上板验证。

负责人：B / cluepiggie。建议分支：`codex/b-motion-mask-protocol-fix`。基准提交以本 PR 实际记录为准。该模块为 A/B 联调使用的帧缓存参考实现，正式 `pipeline_b_module` 适配、双眼实际输入、错误编码和位序仍需 A/B 技术复核及 FengFengKang 最终审批。

## 改动范围

- `fpga/rtl/morphology/morphology_mask_chain.sv`：修正输入握手，严格校验完整帧，新增 `frame_error` 单周期错误脉冲和错误恢复状态。
- `fpga/sim/morphology/tb_morphology_mask_chain.sv`：增加启动同拍、随机输入停顿、输出背压、短帧拒收、短帧后恢复、输出首尾标志回归。
- `fpga/sim/morphology/run_morphology.ps1`、`fpga/sim/morphology/README.md`、`tools/fixtures/morphology_reference.py`：保留并明确可复现入口、算法参考和接口约定。
- `reports/第一部分_Mask_RTL_协议修复验证_2026-10-06.md`：实际工具版本、命令、结果和未验证范围。
- `handoffs/2026-10-06-b-morphology-protocol-fix.md`：新端口、输入语义、A 接手步骤及限制。

未修改第二、三部分算法、A 的共用 pipeline 核心、方案 Word/PDF 或生成工程。

## 接口或行为影响

- `IDLE` 状态下 `in_ready=0`；`frame_start` 只负责把状态置为 `CAPTURE`，下一拍才允许输入握手，避免启动同拍首像素丢失。
- 合法帧必须恰好接收 `WIDTH*HEIGHT` 个像素，并且最后一个像素带 `in_last`。
- 提前 `in_last`、计数到达末尾但缺失正确 `in_last` 时，当前帧进入错误状态，不进入形态学处理，不产生 `out_valid` 或 `done`。
- 新增 `frame_error` 输出，错误帧产生一个时钟周期的脉冲，之后返回 `IDLE`，下一帧可以重新开始。
- 现有位置端口和输出 Mask 打包保持不变；使用旧模块实例化方式的调用者需要补充 `frame_error` 端口或显式悬空连接，调用者需要重新编译。
- 本地 LSB0 打包和 `out_first/out_last` 仍属于功能参考约定，尚未冻结为正式硬件协议。

## 验证证据

- 实际执行的命令/工具版本：

  ```powershell
  & '.\\fpga\\sim\\morphology\\run_morphology.ps1'
  ```

  Icarus Verilog 12.0，`iverilog -g2012` 和 `vvp`。

- 实际结果与报告路径：

  仿真输出：

  ```text
  MORPHOLOGY_PROTOCOL_PASS startup_short_frame_recovery
  ```

  已验证 8×6 功能参考帧、周期性 `out_ready` 背压、启动同拍不握手、随机输入停顿、提前结束短帧、短帧无输出、错误后完整帧恢复、6 个 LSB0 输出字节以及 `out_first/out_last`。

  详细报告：`reports/第一部分_Mask_RTL_协议修复验证_2026-10-06.md`。

- 尚未执行的仿真/综合/上板验证及原因：

  本轮已执行 Icarus 功能仿真；尚未执行安路 TD 综合、资源和时序分析、PH1A90SEG324/DDR3L/PCIe 适配、640×360 双眼实际吞吐、A pipeline_b_module 联调和真实上板。正式仓库检查、合并状态和 `repository-checks` 结果以 PR 上传后的实际状态为准。

## 交接

- [x] 已检查本提交包，不含密钥、权重、二进制、VCD、VVP、build 目录或生成工程；网页上传后仍需核对 PR Files changed。
- [x] 已更新受影响的接口与使用说明，注明 `frame_error` 新端口及重新编译影响。
- [x] 需要另一模块配合时，已明确负责人和步骤：A 连接 `frame_error`，确认正式错误编码、双眼切换、位序和 pipeline_b_module 适配；具体入口见 `handoffs/2026-10-06-b-morphology-protocol-fix.md`。

最终审批与合并由 FengFengKang（蒲公英）确认。本正文不代表已经获得批准；检查通过且获确认后使用 Squash and merge。
