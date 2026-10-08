# 当前 FPGA 开发入口

正式目标为AFH03的PH1A90SEG324，接收双眼640×360搜索图，返回640×360的1 bit运动Mask。A负责Gaussian、同眼帧差、阈值；B负责腐蚀、膨胀、膨胀、腐蚀和Mask打包。

| 模块 | 源码与验证 | 已有证据 |
| --- | --- | --- |
| A前三段 | [rtl/a_motion](rtl/a_motion/motion_front3.v)、[sim/a_motion](sim/a_motion/tb_motion_front3.sv)、[TD工程入口](projects/a_motion_td/create_and_synth.tcl) | 125对像素仿真及目标综合，范围见[A报告](../reports/A职责交付_20261005.md) |
| B后四段/打包参考 | [rtl/morphology](rtl/morphology/morphology_mask_chain.sv)、[sim/morphology](sim/morphology/README.md) | 8×6帧缓存功能参考、启动/短帧/恢复与背压；见[协议修复报告](../reports/第一部分_Mask_RTL_协议修复验证_2026-10-06.md) |

B当前参考仍需转换为可综合的行缓存实现，补帧身份、左右眼、A前三级握手、640×360及完整七级验证。`frame_error`和启动拍语义见[B交接](../handoffs/2026-10-06-b-morphology-protocol-fix.md)，尚未绑定正式PCIe错误码。打包位序和设备布局保持草案。

DDR3L、双向DMA、PCIe、资源时序和正式板级工程依赖厂商IP/SDK与设备；H10预验证单列。本机TD已换为5.6.2，原A综合报告记录的是当时工具版本，本次未重跑综合。不要把小尺寸参考、仿真或综合写成上板通过。

旧计数器、基础图像内核和旧TD工程已转为[本地归档](../archive/README.md)。需要复用时从清单指定来源，选到新任务目录并重新验证。开发先读[当前方案](../plans/current/README.md)、[接口草案](../software/pc_pipeline/contracts/a-motion-v1.md)和个人分工。
