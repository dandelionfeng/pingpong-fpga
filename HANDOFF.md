# 第一部分提交交接说明

负责人：B
任务：FPGA 后四级形态学与 1 bit Mask 打包的功能参考实现。

## 允许修改的目录

- `fpga/rtl/morphology/`
- `fpga/sim/morphology/`
- `tools/fixtures/`
- `reports/`

## 输入与输出

输入是一帧二值图。RTL 依次执行 `erode -> dilate -> dilate -> erode`，使用 3×3 replicate 边界；输出按每 8 个像素低位优先打包为一个字节，并通过 ready/valid 接口输出。

## 本包内容

本包保留仓库相对路径，可直接复制到真实仓库对应位置。`golden/` 中是独立 Python 参考生成的阶段图和 `expected.json`；报告记录了复现命令、结果和未完成验证。

## 复现

在仓库根目录执行：

```powershell
python tools/fixtures/morphology_reference.py
fpga/sim/morphology/run_morphology.ps1
```

已验证工具：Icarus Verilog 12，实际结果应包含 `MORPHOLOGY_MASK_PASS bytes=6 with backpressure`。

## 未完成项

尚未执行安路 TD 综合、资源和时序检查，尚未验证 640×360 实际帧、双眼切换、最终行缓存结构、DDR3L、PCIe、板卡和相机输入。当前低位优先打包位序仍需 A/B 联合评审后冻结。

## 提交建议

本 ZIP 是便于下载和复制的交付包，不是 Git 分支本身。应从最新已评审的 `origin/main` 新建 `codex/b-morphology-mask` 分支，将本包文件复制进仓库，先检查暂存差异，再运行仓库要求的基础检查和本任务仿真，最后提交 PR。由于当前工作目录没有真实 Git 元数据，基准提交号和 PR 编号需在真实仓库中填写。
