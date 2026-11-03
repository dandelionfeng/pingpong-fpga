# BOARD_ENVIRONMENT_REPORT — AFH03 / RK3576J

日期：2026-11-03
分支：`codex/afh03-board-validation-20261103`

## 1. 结论

| 项 | 状态 |
|---|---|
| AFH03 实物 | **BLOCKED（未连接）** |
| RK3576J 芯片信息 | **NOT TESTED（无板）** |
| RKNPU 驱动版本 | **NOT TESTED（无板）** |
| RKNN Runtime 版本 | 官方 2.5.0 已获取并核验；板端实际版本 **BLOCKED** |
| RKNN Toolkit2 | 2.5.0（模型转换环境） |
| rknn_api.h | 官方 v2.5.0 已获取并核验；板端头文件 **BLOCKED** |
| librknnrt.so | 官方 2.5.0，SHA256/版本已核验；板端实际库 **BLOCKED** |
| NPU 双核 | API/硬件能力存在；实际 core 负载 **BLOCKED** |
| 官方推荐转换配置 | `target_platform='rk3576'`、960、FP16 |
| RK3576 / RK3588 兼容边界 | 模型 target-specific；RK3588 simulator 只能做代理，不能当板端 |

## 2. 官方资料核查

Rockchip 官方 RKNN Toolkit2 README 明确列出支持平台包含 **RK3576 Series**：

- https://github.com/airockchip/rknn-toolkit2
- https://github.com/airockchip/rknn-toolkit2/blob/master/CHANGELOG.md

CHANGELOG 的 **v2.5.0** 包含 runtime 修复/多输入输出优化等；v2.5.0 是当前模型转换使用的版本。

第三方 AFH03/RK3576 实测指南给出配套基线（不是本项目板子）：

- [Seeed RK3576 RKNN2 部署指南](https://sensecraft.seeed.cc/ai-lab/zh/tools/rk/rk3576-cnn-rknn2-deploy)
- 该指南实测：RKNPU 驱动 **0.9.8**，Runtime/Toolkit Lite2 **2.3.2**，并要求 RKNPU 驱动不低于 **0.9.2**；
- 这证明 RK3576 的常见板端基线是 2.3.2，**不等于** 2.5.0 已安装；本项目要求 2.5.0，必须单独部署并核验。

## 3. 官方 RKNN 2.5.0 资产（本轮实际下载/核验）

来源：`airockchip/rknn-toolkit2` tag `v2.5.0` 的
`rknpu2/runtime/Linux/librknn_api/`。

| 文件 | 大小 | SHA256 | 实际版本 |
|---|---:|---|---|
| `librknnrt.so`（aarch64） | 8,189,368 | `4b6cc575bedf8952b13db4b1190fa3b3d2ac213f00be774ff6ccd19d651970c0` | `librknnrt version: 2.5.0 (74ea630ce8@2026-09-30T09:41:17)` |
| `rknn_api.h` | 36,524 | `2d4160cd868efd7b83a72587e411c16d6972da5876e067bd73665cea778ce666` | 官方 2026 版头文件 |

获取脚本：

```bash
sh tools/fetch_rknn_2.5.0.sh ./rknn-2.5.0
```

脚本只下载到当前目录，不覆盖 `/usr/lib`、不修改固件。

模型由 Toolkit2 **2.5.0** 生成，模型 header 记录构建时间 `2026-09-29`；Runtime 2.5.0 构建时间为 `2026-09-30`。  
**版本匹配关系：Toolkit2 2.5.0 ↔ Runtime 2.5.0 ↔ 8 输出 FP16 模型。** 这是本轮确定的目标组合。

## 4. 现有板端 2.3.x 的处理

生产板可能已有 `librknnrt.so` 2.3.x（例如 Seeed 基线 2.3.2）。本轮策略：

1. **不覆盖系统 `/usr/lib/librknnrt.so`**；
2. 将 2.5.0 放在应用目录 `lib/`，运行时用 `LD_LIBRARY_PATH` 指向；
3. C++ 代码已把 8 输出要求写成 **≥2.5.0**，2.3.x 会明确拒绝，不会静默加载；
4. 若板厂只允许系统库，需由板厂提供 2.5.0 的配套 BSP/固件；本阶段不升级固件。

## 5. NPU 双核

`rknn_api.h` 提供：

```text
RKNN_NPU_CORE_0
RKNN_NPU_CORE_1
RKNN_NPU_CORE_0_1
RKNN_NPU_CORE_AUTO
```

实际核心数/负载要板端读：

```bash
cat /sys/kernel/debug/rknpu/load
```

**没有板，不能声称双核可用或双核更快。** 本轮只完成 API/代码路径准备和单核/双核测试脚本。

## 6. RK3576 与 RK3588 的边界

- Toolkit 的 `target_platform='rk3576'` 与 `'rk3588'` 是不同目标；
- RK3588 simulator 只能作为量化误差代理，**不能替代 RK3576 板端结果**；
- 8 输出模型的 `target_platform` 必须为 `rk3576`；本模型文件由 2.5.0 生成，实际 target 以模型 header/转换日志为准；
- 不能把一个 RK3588 上转换的模型直接当 RK3576 交付。

## 7. 板端实际检查（待执行）

```bash
uname -a
cat /proc/device-tree/compatible | tr -d '\0'
cat /sys/kernel/debug/rknpu/version
cat /sys/kernel/debug/rknpu/load
ldconfig -p | grep rknn
strings /usr/lib/librknnrt.so | grep 'librknnrt version'
python3 -c 'import rknnlite; print(rknnlite.__version__)'
```

`tools/afh03_deployment_diagnostic.sh` 已准备好，会输出
`AFH03_DEPLOYMENT_DIAGNOSTIC.txt`。

## 8. 状态

**AFH03 环境：BLOCKED（无实物）。** 官方 2.5.0 Runtime/Header 已取得并核验，版本关系明确；板端驱动、实际库、NPU 负载和核心数仍需在 AFH03 上执行。
