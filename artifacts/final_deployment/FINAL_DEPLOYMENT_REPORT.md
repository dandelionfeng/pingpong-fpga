# FINAL_DEPLOYMENT_REPORT — AFH03 / RK3576J

日期：2026-11-03
仓库：`dandelionfeng/pingpong-fpga`
分支：`codex/final-afh03-deployment-20261103`
基线：`c19cf40d3b065702c62fbd3a682e7221d0ba8d17`

> 本轮完成了代码修复、8 输出适配、PC/模拟器回归和文档；真实板端加载/FPS 仍受硬件和 Runtime 版本阻塞。

## 1. 执行摘要

- **已实现** 8 输出 DFL 适配，保留 1/6 输出模式；
- **已实现** 输出 dtype 统一 `want_float=1`，避免 INT8 重复反量化；
- **已实现** 单次 sigmoid；只选第一个 3 通道 logits；
- **已实现** runtime 版本策略：8 输出要求 ≥2.5.0，2.3.0 明确拒绝；
- **实际 509 张 C++ DFL 解码**通过，指标与 FP32 基线一致；
- **OpenCV 4.13 与 C_ACTUAL 构建**通过；
- **ARM64/板端/FPS** 仍 BLOCKED；
- **GitHub 推送**结果见第 7 节。

## 2. 代码变更

| 文件 | 变更 |
|---|---|
| `source/native/rk_runtime/c_rknn/runtime_session.cpp` | 新增 `kFlatDfl` 8 输出分支、版本策略、`want_float=1`、8 输出释放 |
| `.../runtime_session.hpp` | 接口不变 |
| `.../dfl_flat_decoder.hpp` | 新增 8 输出 DFL 解码与布局识别 |
| `.../output_layout_policy.hpp` | 新增 1/6/8 输出模式选择 |
| `.../tests/flat_dfl_test.cpp` | 新增 8 输出/DFL/模式/边界测试 |
| `.../CMakeLists.txt`（c_actual） | 支持 Linux `libonnxruntime.so`，Windows `.lib` |
| `README.md` | 增加最终部署说明 |

未修改：`.rknn`、`.onnx`、模型权重、BallTrack、Hand 测量、Racket 过滤、960 输入、GRAY8 接口。

## 3. 模型与 Runtime 契约

实际模型 **8 输出**：

```text
output0 [1,7,18900], Reshape [1,64,18900], Sigmoid [1,3,18900],
Conv [1,64,120,120], [1,128,60,60], [1,256,30,30],
boxes [1,4,18900], scores [1,3,18900]
```

代码选择：

- DFL：`[1,64,18900]`；
- 分类：第一个 `[1,3,18900]`（index 2，`Sigmoid_769`），**不再对 `scores` 二次 sigmoid**；
- 忽略 concat/中间特征/已解码 boxes/scores；
- `want_float=1` 一次取得 8 个输出，由 runtime 统一转 float；
- 释放 `rknn_outputs_release(ctx,8,...)`。

版本：

- 1/6 输出：2.3.0 或 ≥2.5.0；
- 8 输出：≥2.5.0；
- 2.3.0 + 8 输出：明确报错，不绕过。

## 4. 509 张精度

| 类别 | FP32 ONNX | FP16 RKNN 模拟器 | INT8 RKNN 模拟器 | C++ flat DFL |
|---|---:|---:|---:|---:|
| Ball P/R/F1 | .8226/.5100/.6296 | .8095/.5100/.6258 | .7833/.4700/.5875 | **.8226/.5100/.6296** |
| Hand P/R/F1 | .6913/.5580/.6176 | .6917/.5589/.6182 | .6726/.5486/.6043 | **.6913/.5580/.6176** |
| Racket P/R/F1 | .7600/.7557/.7578 | .7644/.7557/.7600 | .7557/.7557/.7557 | **.7600/.7557/.7578** |

验收：

- FP16 / C++：Ball R 0.510 ≥ .49，Hand F1 .618/.618 ≥ .60，Racket R .756 ≥ .73 → **PASS**
- INT8：Ball R .470 < .49 → **FAIL**，不作为默认正式交付。

C++ 509 逐图结果：`evidence/cpp_flat_509.json`（509 项）；单帧误差 score 5.96e-08、中心/宽高 9.16e-05 px，无系统性偏移。

## 5. 构建与测试

| 项 | 状态 |
|---|---|
| OpenCV 4.13.0 构建 | **PASS** |
| C_ACTUAL + OpenCV 4.13 | **PASS**（263,734 B） |
| Windows C_ACTUAL 3.4.1 | **PASS** |
| 父级 source/native | **BLOCKED**（RKNN runtime） |
| ARM64 交叉编译 | **BLOCKED**（无工具链/SDK/ARM64 OpenCV） |
| 1/6/8 输出单测 | **PASS** |
| runtime_session 语法检查 | **PASS**（host stub） |
| C++ 509 DFL | **PASS** |
| 509 FP16/FP32 | **PASS** |
| 509 INT8 | **FAIL**（Ball R） |
| RK3576J 实机 | **BLOCKED** |
| NPU FPS | **BLOCKED** |

## 6. 18 个必答问题

1. **当前 V3 FP16 能否被生产 Runtime 正确加载？**  
   **BLOCKED**。代码已支持 8 输出；但无板、无 RKNN ≥2.5.0 runtime，未实际 `rknn_init`。

2. **八输出问题是否解决？**  
   **PASS（代码级）**。`kFlatDfl` 分支、布局识别、DFL、单 sigmoid、509 张 C++ 解码均通过；**板端加载 NOT TESTED**。

3. **Toolkit 与 Runtime 版本是否兼容？**  
   **FAIL（当前组合）**。模型由 Toolkit 2.5.0 生成；生产 Runtime 2.3.0 不能加载 8 输出，代码要求 ≥2.5.0。缺少 2.5.0 runtime/板，**BLOCKED**。

4. **C++ DFL 解码是否通过数值回归？**  
   **PASS**。C++ 509 指标与 FP32 一致；单帧误差 <1e-4 px / <1e-7 score。

5. **509 张验证集是否通过？**  
   **FP16/C++ PASS；INT8 FAIL**（Ball R 0.470）。

6. **Ball Recall 是否保持 0.49 以上？**  
   FP16/C++ **0.5100 PASS**；INT8 **0.4700 FAIL**。

7. **Hand F1 是否保持 0.60 以上？**  
   FP16 **0.6182 PASS**；C++ **0.6176 PASS**；INT8 0.6043 但整体不达标。

8. **BallTrack 是否完全没有被破坏？**  
   **PASS（设计保护）**。未改 BallTrack 输入/跟踪/状态/判罚；YOLO ball 未写入 `result.balls`。

9. **Racket 是否仍按设计在结果传递层过滤？**  
   **PASS（设计保护）**。过滤仍在 NPU→DFL→NMS 之后，模型仍保留第三类。

10. **base_conf=0.005 是否真正生效？**  
    **代码/单测 PASS；板端 BLOCKED**。配置链和阈值边界测试通过；实际模型加载未执行。

11. **C_ACTUAL 是否可以独立构建？**  
    **PASS**（Linux/OpenCV 4.13、Windows/3.4.1）。

12. **ARM64 是否真实编译？**  
    **BLOCKED**。无 `aarch64-linux-gnu-g++`、无 ARM64 OpenCV、无 `librknnrt.so`。

13. **是否在 RK3576J 上实际加载？**  
    **BLOCKED**。无板、无 `/dev/rknpu`、ADB 空。

14. **NPU FPS 是多少？**  
    **没有实测 FPS**。不提供 PC 替代值。

15. **30/50/90 FPS 是否达到？**  
    **全部 NOT TESTED**。

16. **GitHub 是否已经成功推送？**  
    见第 7 节（推送后填写 PASS/FAIL 及错误）。

17. **最终 Commit SHA？**  
    见最终回复与远程分支 HEAD；报告本身不写自引用 SHA。

18. **队长现在应该下载哪个版本？**  
    **不要下载为“正式上板件”**。当前只能下载 `codex/final-afh03-deployment-20261103` 用于继续板端验证；正式生产仍用原发布包，直到 8 输出 + RKNN ≥2.5.0 在 AFH03 实测通过。FP16 精度可作候选，INT8 不可。

## 7. GitHub

目标分支：

```text
codex/final-afh03-deployment-20261103
```

推送命令：

```bash
git push -u origin codex/final-afh03-deployment-20261103
```

结果：**PASS**。`git push -u origin codex/final-afh03-deployment-20261103` 已成功；远程分支存在，远程 HEAD 与本地 HEAD 一致。最终 Commit SHA 见最终回复和远程分支 HEAD（本报告不写自引用 SHA）。

推送前曾遇到 Windows Git 网络 `Connection was reset` / `Failed to connect`；改用 WSL 的 GitHub 连通路径 + 已验证的 GitHub 凭据后成功。未 force push、未覆盖 main。

## 8. 最终结论

**代码级 8 输出适配完成、C++ 509 精度通过、C_ACTUAL/OpenCV 4.13 构建通过；但真实 RK3576J 加载和 FPS 仍 BLOCKED。当前不能作为“已上板正式交付”，可交给队长作为板端验证候选。**
