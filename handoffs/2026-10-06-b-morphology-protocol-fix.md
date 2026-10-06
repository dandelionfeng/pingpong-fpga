# B 第一部分 Mask RTL 协议修复交接

- 负责人：B / cluepiggie。
- 目标：修复评审指出的启动同拍丢首像素和短帧误处理。
- 修改文件：`fpga/rtl/morphology/morphology_mask_chain.sv`、`fpga/sim/morphology/tb_morphology_mask_chain.sv`、`fpga/sim/morphology/README.md`。
- 新增接口：`frame_error`，短帧/错误帧产生单周期脉冲；错误帧不产生 `out_valid` 或 `done`。
- 输入语义：`frame_start` 后进入 `CAPTURE`；只有 `state==CAPTURE` 时 `in_ready=1`。合法帧必须恰好 `WIDTH*HEIGHT` 个传输，并在最后一个传输带 `in_last`。
- 已验证：Icarus Verilog 12.0；启动同拍、随机停顿、背压、短帧拒收和错误后恢复通过。
- 接手要求：A 需要在 pipeline_b_module 适配层连接 `frame_error`，并确认正式错误编码、双眼切换和位序；旧实例化需补端口连接。
- 未验证：安路 TD、综合、资源时序、DDR3L、PCIe、640×360 实际帧率、上板。

