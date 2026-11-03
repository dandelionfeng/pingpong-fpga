# RKNN_RUNTIME_COMPATIBILITY — AFH03 / RK3576J

日期：2026-11-03

## 1. 目标组合

```text
模型转换：rknn-toolkit2 2.5.0
模型：V3 FP16 960x960, 8 outputs
Runtime：librknnrt.so 2.5.0 (74ea630ce8@2026-09-30)
Header：rknn_api.h v2.5.0
Target：rk3576
```

这是本轮确定的 **Toolkit 2.5.0 ↔ Runtime 2.5.0 ↔ 8 输出模型** 组合。

## 2. 实际资产核验

| 文件 | 版本/大小 | SHA256 |
|---|---|---|
| `librknnrt.so` | 2.5.0，8,189,368 B | `4b6cc575bedf8952b13db4b1190fa3b3d2ac213f00be774ff6ccd19d651970c0` |
| `rknn_api.h` | v2.5.0，36,524 B | `2d4160cd868efd7b83a72587e411c16d6972da5876e067bd73665cea778ce666` |
| `v3_960_fp16_dfl_layout.rknn` | 13,038,908 B | `1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b` |

Runtime 版本字符串实际输出：

```text
librknnrt version: 2.5.0 (74ea630ce8@2026-09-30T09:41:17)
```

模型 header 的构建时间与之同代（2026-09-29/30），模型由 Toolkit 2.5.0 生成。

## 3. 代码兼容策略

`runtime_session.cpp`：

- 1/6 输出：Runtime 2.3.0 或 ≥2.5.0；
- 8 输出：**≥2.5.0**；
- 2.3.x + 8 输出：明确失败，不绕过；
- 不移除版本检查，不修改固件。

8 输出适配：

```text
DFL [1,64,18900] + 第一个 [1,3,18900]
want_float=1（FP16/FP32/INT8 统一由 runtime 转 float）
不手工 (q-zp)*scale
只做一次 sigmoid
```

## 4. 与现有 2.3.x 板端的关系

RK3576 常见板端基线（第三方实测指南）是 Runtime 2.3.2；本模型需要 2.5.0：

- 不能把 2.3.2 的 `librknnrt.so` 当作 2.5.0；
- 不覆盖系统库；把 2.5.0 放应用目录，用 `LD_LIBRARY_PATH`；
- 若必须系统级安装，需板厂/项目批准并保留备份；
- 2.3.2 + 8 输出模型会触发明确错误，不会误跑。

## 5. API / 双核

- 官方 header 提供 `RKNN_NPU_CORE_0/1/0_1/AUTO`；
- `rknn_set_core_mask` 在 2.5.0 runtime 中存在，ARM 链接通过；
- 实际 NPU 核心数/负载需要板端 `/sys/kernel/debug/rknpu/load`，本轮无板 **BLOCKED**；
- 不声称双核一定更快。

## 6. 兼容性状态

| 项 | 状态 |
|---|---|
| Toolkit 2.5.0 支持 RK3576 | **PASS（官方 README）** |
| Runtime 2.5.0 资产真实存在 | **PASS** |
| Header/Runtime 2.5.0 编译链接 | **PASS（ARM64 link）** |
| 8 输出模型与 Runtime 2.5 代码契约 | **PASS（代码/单测）** |
| 板端实际 2.5.0 加载 | **BLOCKED（无板）** |
| 板端实际驱动版本 | **BLOCKED** |
| 2.3.x 直接加载 8 输出 | **FAIL（预期，明确拒绝）** |
