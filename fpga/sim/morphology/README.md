# B 模块第一部分：后四级形态学与 Mask 打包

当前版本是功能优先的帧缓存参考 RTL，输入一帧二值图，完成 `腐蚀→膨胀→膨胀→腐蚀`，使用 3×3 邻域和 replicate 边界，再按低位优先每 8 像素打包一字节。它用于接口和算法联调，尚未声称为 PH1A90SEG324 的行缓存、综合或时序结果。

运行：

```powershell
python tools/fixtures/morphology_reference.py
fpga/sim/morphology/run_morphology.ps1
```

仿真输入是 8×6 的一个 4×4 前景块和一个孤立噪声点；独立 Python 参考生成 golden 图和字节。640×360 实际尺寸、双眼切换、短帧、复位覆盖和行缓存替换仍待后续任务完成。

当前低位优先位序只是本地测试约定，尚未经 A/B 联合评审冻结。
