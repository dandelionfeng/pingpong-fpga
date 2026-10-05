# 第一部分：后四级形态学与 Mask 打包

当前版本是 B 模块后四级的功能优先 RTL：3×3 replicate 边界，顺序为腐蚀、膨胀、膨胀、腐蚀；每 8 个二值像素按低位优先打包成 1 字节。

## 复现

在仓库根目录执行：

```powershell
python tools/fixtures/morphology_reference.py
fpga/sim/morphology/run_morphology.ps1
```

测试输入为 8×6 二值图，包含 4×4 前景块和一个孤立点。独立 Python 参考和 RTL 都应得到：

```text
1f 1f 1f 1f 1f 1f
MORPHOLOGY_MASK_PASS bytes=6 with backpressure
```

testbench 周期性拉低 `out_ready` 并核对接收的六个输出字节；当前没有独立断言逐拍检查背压期间的数据稳定性，也没有逐级 RTL 中间图对照。

## 当前范围

结果是 Icarus Verilog 功能仿真，固定了算法顺序、边界规则、打包位序和基本 ready/valid 语义。当前 RTL 使用帧缓存参考结构，尚未完成 PH1A90SEG324 的行缓存替换、TD 综合、资源/时序、DDR3L、PCIe 或上板验证。
