# AFH03_DEPLOYMENT_VALIDATION_REPORT

日期：2026-11-03
仓库：`dandelionfeng/pingpong-fpga`
基线：`b4495fd4eb8cd798ba38105f64e2a51280e85647`
分支：`codex/afh03-deployment-20261103`
工作树：`D:\pp_fix_work`

## 0. 最终结论

**本轮 OpenCV 4.13 与 C_ACTUAL 独立构建成功；但 RK3576J 部署链仍未闭环。**

三个硬阻塞：

1. **模型与生产 runtime 契约 FAIL**：两个目标 `*_dfl_layout.rknn` 实际都是 **8 输出**，`runtime_session.cpp` 只接受 **1 或 6** 输出，`rknn_init` 后会在输出数量检查处失败。
2. **无 RK3576J 板 / 无 RKNN runtime**：没有 `/dev/rknpu`、`librknnrt.so`、ADB 设备；无法做 `rknn_init`、NPU 精度和 FPS。
3. **无 ARM64 工具链/ARM64 OpenCV**：没有 `aarch64-linux-gnu-g++`，因此没有真实 AArch64 编译。

因此：**不能交付队长为“已上板验收”。** FP16 精度达标，但部署集成和板端性能尚未通过。

## 1. 实际完成的构建

| 项 | 状态 | 证据 |
|---|---|---|
| OpenCV 4.13.0 源码构建 | **PASS** | 4.13.0；core/imgproc/imgcodecs/videoio/calib3d/features2d |
| C_ACTUAL + OpenCV 4.13 独立构建 | **PASS** | `libc_actual.a` 263,734 B |
| C_ACTUAL Linux 动态链接 | **PASS** | `libopencv_core.so.413`、`libonnxruntime.so.1` |
| Windows C_ACTUAL 3.4.1 回归 | **PASS** | configure/build rc=0 |
| 父级 `source/native` 完整构建 | **BLOCKED** | `rk_runtime/c_rknn` 要求 RKNN header + board runtime |
| ARM64 真实交叉编译 | **BLOCKED** | 无工具链/SDK/ARM64 OpenCV |
| RK3576J 实机 | **BLOCKED** | 无板 |

详细命令、日志和动态库证据见 `BUILD_REPORT.md` 与 `evidence/`。

## 2. 模型与输出属性（实际解析）

文件哈希：

```text
1bcff6ff...cad0b  v3_960_fp16_dfl_layout.rknn  (13,038,908 B)
ccd13472...ef853  v3_960_int8_dfl_layout.rknn  (9,860,593 B)
4e63796c...ce3f8  pingpong_v3_960_split_keepall.onnx
```

从 `.rknn` 容器 header 实际解析：

```text
FP16: 8 outputs, all quant_dtype=float16, no scale/zp
INT8: 8 outputs, all quant_dtype=float32, qtype=asym, scale/zp empty
```

8 个输出：

```text
output0             [1,7,18900]
onnx::Reshape_725   [1,64,18900]   # DFL 16-bin
onnx::Sigmoid_769   [1,3,18900]    # class logits (pre-sigmoid)
onnx::Conv_607      [1,64,120,120]
onnx::Conv_643      [1,128,60,60]
onnx::Conv_679      [1,256,30,30]
boxes               [1,4,18900]
scores              [1,3,18900]
```

**这与模型卡写的“2 outputs (dfl + scores_logits)”不一致；以实际文件为准。**

### 与生产 runtime 的冲突

`runtime_session.cpp`：

```cpp
if (count.n_input != 1 || (count.n_output != 1 && count.n_output != 6))
  throw std::runtime_error("Expected one input and one primary output");
```

实际 8 输出 → 直接抛异常。6 输出分支还要求 6 个 raw-head 形状，**也不匹配**本模型的 8 个张量。

静态检查实际输出：`MODEL_RUNTIME_CONTRACT=FAIL`（`evidence/model_contract_fp16.txt`、`model_contract_int8.txt`）。

## 3. 量化与精度

509 张固定 val 实际执行：

| 模型 | Ball P/R/F1 | Hand P/R/F1 | Racket P/R/F1 |
|---|---|---|---|
| FP32 ONNX | 0.8226 / **0.5100** / 0.6296 | 0.6913 / 0.5580 / 0.6176 | 0.7600 / 0.7557 / 0.7578 |
| FP16 RKNN（模拟器） | 0.8095 / **0.5100** / 0.6258 | 0.6917 / 0.5589 / **0.6182** | 0.7644 / 0.7557 / 0.7600 |
| INT8 RKNN（模拟器） | 0.7833 / **0.4700** / 0.5875 | 0.6726 / 0.5486 / **0.6043** | 0.7557 / 0.7557 / 0.7557 |

验收：

- FP16：Ball R 0.510 ≥ 0.49；Hand F1 0.6182 ≥ 0.60；Racket R 0.7557 ≥ 0.73 → **PASS（模拟器代理）**
- INT8：Ball R 0.470 < 0.49 → **FAIL**，不得作为正式部署件

FP16/INT8 是 `rknn-toolkit2 2.5.0 simulator, target_platform=rk3588` 代理，不是 RK3576J 板端。FP32 是 ONNX Runtime CPU 实际执行。

详见 `QUANTIZATION_VALIDATION.md`、`MODEL_ACCURACY_COMPARISON.md`。

## 4. base_conf=0.005

- `app/rk/model-config-int8.json` 实际为 `base_conf: 0.005`、ball 0.02、hand 0.1、racket 0.1。
- 第一阶段代码链测试 5/5 PASS；C++ 阈值边界测试 PASS（`.005` 保留 0.01 候选，非法值拒绝）。
- **但目标模型无法被生产 runtime 加载**，所以 `base_conf=0.005` 在部署链路上没有实际执行证据。

结论：**阈值逻辑 PASS；部署生效性 BLOCKED/FAIL。**

## 5. DFL 解码

- Python 参考 DFL 解码在 509 张上实际运行，FP32/FP16 指标与基线一致，说明 softmax(16)→期望→dist2bbox→letterbox 反变换→sigmoid 的数学正确。
- **生产 C++ 6-head DFL 分支没有被可加载模型执行**；不能写成“C++ 生产 DFL 已验证”。
- 独立 `rknn_v3_detect_dfl.cpp` 支持 DFL 张量，但本轮没有在板上编译/运行，且它不是正式判罚链路。

## 6. 性能

**没有 RK3576J 实测 FPS。** 无板、无 RKNN runtime，不能用 PC 模拟器/PC CPU 代替。30/50/90 FPS 均 **NOT TESTED**。

现有计时入口：`input_layout_ms`、`rknn_inputs_set_ms`、`rknn_run_ms`、`rknn_outputs_get_ms`、`cpu_dfl_ms`；缺独立 `nms_ms` 和采集/letterbox 分阶段统计。详见 `PERFORMANCE_REPORT.md`。

## 7. AFH03 板端诊断

`AFH03_DEPLOYMENT_DIAGNOSTIC.txt` 已生成；本轮在 Windows 上运行，输出：

```text
host=LAPTOP-ONROQI2O
RK3576_COMPATIBLE=NOT_TESTED
BOARD_STATUS=BLOCKED_NOT_AFH03
```

该文件不是板端报告，不能当板端 PASS。板端直接运行：

```bash
sh tools/afh03_deployment_diagnostic.sh \
  --binary /userdata/build/motion7_chain \
  --model /userdata/v3_960_fp16_dfl_layout.rknn \
  --out /userdata/AFH03_DEPLOYMENT_DIAGNOSTIC.txt
```

脚本会检查芯片、内核、RKNPU 驱动、runtime、toolkit、NPU 核/频率、RGA、OV9281 GRAY8、`ldd` 和模型 SHA。

## 8. 必答问题

1. **OpenCV 4.13 是否构建成功？**
   **是（PASS）**：4.13.0 源码构建，C_ACTUAL 使用 4.13 构建成功，`ldd` 显示 `.so.413`。

2. **C_ACTUAL 是否能够独立构建？**
   **是（PASS）**：Linux/OpenCV 4.13 和 Windows/OpenCV 3.4.1 均独立 configure/build 成功。

3. **ARM64 是否真实编译成功？**
   **否（BLOCKED）**：无 `aarch64-linux-gnu-g++`、无 ARM64 OpenCV、无 `librknnrt.so`、无板。未执行。

4. **FP16 是否可以正式部署？**
   **精度上可以，集成上不可以（NO-GO）**。FP16 精度达标（Ball R 0.510/Hand F1 0.618/Racket R 0.756），但目标模型 8 输出与生产 runtime 1/6 输出契约冲突；必须先加 DFL 适配层或换 6-head 模型，并在板上验证。

5. **INT8 是否达到精度要求？**
   **否（FAIL）**：Ball Recall 0.470 < 0.49；Hand F1 0.6043、Racket R 0.7557 达标，但 Ball 不达标，不得作为正式部署件。

6. **base_conf=0.005 是否真正生效？**
   **代码链/单测 PASS；部署链 BLOCKED**。目标模型无法被生产 runtime 加载，不能声称已生效。

7. **DFL 解码是否正确？**
   **Python 参考数学 PASS（509 张实际执行）**；生产 C++ 路径 **NOT TESTED / 模型不可加载**，不能整体判定 PASS。

8. **RK3576J NPU 是否实际运行？**
   **否（BLOCKED）**：无板、无 `/dev/rknpu`、无 `librknnrt.so`、ADB 空。

9. **实测 FPS 是多少？**
   **没有实测 FPS**。不能给出 PC 模拟器/PC CPU 替代值。

10. **是否达到 30 / 50 / 90 FPS？**
    **全部 NOT TESTED**；没有板端数据。

11. **是否可以交付队长？**
    **当前 NO-GO。** 可交付的是：OpenCV 4.13 构建结果、509 张精度对照、模型/runtime 契约 FAIL 证据、诊断脚本和学习报告；**不能交付“已上板/可正式部署”的结论**。

## 9. 建议的最小下一步

1. 先解决模型契约：把生产 runtime 增加 8 输出 DFL 分支（或生成 6-head raw 模型），并在 PC 上用同一 509 张做逐框对齐。
2. 在 AFH03 上用 **runtime ≥ 2.5.0**（当前 C++ 硬性要求 2.3.0，与 2.5.0 转换模型不匹配），执行 `rknn_init`、输出属性 query、509 张板端精度。
3. 再测 50 预热 + 500 正式帧，单核/双核/auto，输出 Mean/P50/P95；报告 NPU、DFL、NMS、完整流水线分开。
4. 不要用 INT8 替换 FP16；INT8 Ball R 0.470 不达标。

## 10. Git

```text
branch: codex/afh03-deployment-20261103
base:   b4495fd4eb8cd798ba38105f64e2a51280e85647
```

本轮只新增 `artifacts/deployment_validation/` 和一个 CMake 的 Linux ONNX 库查找修复；未修改模型、未合并 main、未推送正式发布。
