# B 模块第一部分：后四级形态学与 Mask 打包

当前版本是功能优先的帧缓存参考 RTL，输入一帧二值图，完成 `腐蚀→膨胀→膨胀→腐蚀`，使用 3×3 邻域和 replicate 边界，再按低位优先每 8 像素打包一字节。它用于接口和算法联调，尚未声称为 PH1A90SEG324 的行缓存、综合或时序结果。

运行：

```powershell
python tools/fixtures/morphology_reference.py
fpga/sim/morphology/run_morphology.ps1
```

仿真输入是 8×6 的一个 4×4 前景块和一个孤立噪声点；独立 Python 参考生成 golden 图和字节。回归还覆盖启动同拍、随机输入停顿、短帧拒收、错误恢复、输出背压和 LSB0 打包。

接口约定：`frame_start` 只负责把模块从 `IDLE` 置入 `CAPTURE`，`IDLE` 时 `in_ready=0`，因此启动同拍的 `in_valid/in_pixel` 不会被错误地计为已接收。完整帧必须恰好收到 `WIDTH*HEIGHT` 个像素，并在最后一个像素带 `in_last`；提前或缺失 `in_last` 会丢弃当前帧、产生一个时钟周期的 `frame_error`，不产生 `out_valid/done`，随后回到 `IDLE` 等待下一帧。

本次修复新增 `frame_error` 输出，使用旧实例化方式的调用者需要补充该端口或显式悬空连接。

当前低位优先位序只是本地测试约定，尚未经 A/B 联合评审冻结。
