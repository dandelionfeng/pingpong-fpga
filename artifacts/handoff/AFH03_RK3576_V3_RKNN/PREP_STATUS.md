# AFH03 / RK3576J 部署准备状态（PC 端已完成，板端 BLOCKED）

日期：2026-10-30　分支：`codex/c-pc-detector`　起点提交：`bc998ae`

## 0. 一句话结论

**RKNN 转换与板端测试 BLOCKED**（无板子连接、无 rknn-toolkit2 wheel）；
PC 端已完成：环境审计、**ONNX 单输出修复**、**640 vs 960 精度对照**、校准清单、
转换脚本、RKNN C++ 推理程序（含双核调度与分阶段计时）、**C++ 解码路径核验**。

## 1. 第一阶段：环境审计（实测）

| 检查项 | 结果 |
| --- | --- |
| adb / USB Rockchip 设备 | ❌ 未安装 adb；`Get-PnpDevice` 无 AFH03/Rockchip/Maskrom 设备 |
| 板子网络 | `192.168.1.10` ❌、`192.168.0.10` ❌；`192.168.137.2` 能 ping 但 **22 端口关闭**（是 Windows ICS 网关，不是板子） |
| SSH | 有 `ssh.exe`，但无目标可连 |
| **RK3576J 型号 / 内核 / RKNPU 驱动 / RKNN Runtime** | ❌ **无法获取**（板子不可达） |
| `/dev/rknn*`、`/sys/kernel/debug/rknpu/load` | ❌ 无法检查 |
| rknn-toolkit2 | ❌ 未安装；`pip download rknn-toolkit2==2.3.0` → **No matching distribution**（本机 Python 3.12/3.13，官方只发 Linux x86_64 的 py3.6–3.11 wheel） |
| CPU / GPU | Intel i9-14900HX / RTX 4060 Laptop（PC 端） |
| 现有 RKNN 示例 | ❌ 仓库内无 |

> **明确声明：本机既无 AFH03 实物连接，也无法运行 rknn-toolkit2。
> 本轮所有"转换脚本/校准清单/C++ 程序"都是可在板端或 Linux 转换机上直接运行的准备件，
> 没有产生任何 `.rknn` 文件，也没有任何板端数据。**

## 2. 第二阶段：统一三分类链路（只读核对，未改 C++）

| 问题 | 结论 |
| --- | --- |
| V3 是否同时产生三类 | ✅ 输出 `[1,7,18900]`，类别 `0/1/2` |
| Ball 是否被现有代码过滤 | ✅ **是**（`perception_engine.cpp` 明确丢弃 ball，ball 唯一来源是 BallTrack） |
| BallTrack 是否独立运行 | ✅ 是，与 YOLO 并行，两条链路互不干扰 |
| 是否两个球源竞争 | 当前**没有**（YOLO 的球被丢弃）；若启用 V3 的 ball 输出就会出现双源，需 B 模块评审 |
| 重复预处理 | ✅ 有：unified / hand / racket 三条路径各自做 Gray3+letterbox（统一模式下只跑一次，可接受） |

## 3. 第三/四阶段：ONNX → RKNN 的关键发现

### 3.1 现有 V3 ONNX 有 **6 个输出**（必须修）

```
inputs : images [1,3,960,960]
outputs: output0          [1,7,18900]      <- 真正要的
         onnx::Reshape_725[1,64,18900]     <- DFL 中间
         onnx::Sigmoid_769[1,3,18900]
         onnx::Conv_607   [1,64,120,120]
         onnx::Conv_643   [1,128,60,60]
         onnx::Conv_679   [1,256,30,30]
```

多输出会让 RKNN 图里带 4 个无用分支（增大模型、增加转换风险）。
**已用 ultralytics 官方导出重做**：

| 模型 | 节点数 | 输出 | 大小 | SHA256 |
| --- | ---: | --- | ---: | --- |
| 原 V3（6 输出） | 397 | 6 | 12,161,114 | `b779c88e…`（**未改动，仍是交付件**） |
| **单输出版（转换用）** | **234** | **1** | 12,477,398 | `39a9eb3a62da2d58373291747b7a740dc6d652ea8f2c850d77509aeae3b2301e` |

**精度一致性实测**（同一 509 张 val，同阈值）：

| 类别 | 原 V3 | 单输出版 |
| --- | --- | --- |
| Ball | 0.823 / 0.510 / 0.630 / 0.492 | **完全相同** |
| Hand | 0.691 / 0.558 / 0.618 / 0.504 | **完全相同** |
| Racket | 0.760 / 0.756 / 0.758 / 0.689 | **完全相同** |

（P/R/F1/AP50 逐位一致；逐帧逐框存在 ≤1.16e-03 的 logits 浮点差，不影响指标。）

### 3.2 算子清单（供 RKNN 兼容性参考）

```
Conv 64, Sigmoid 58, Constant 80, Mul 76, Concat 21, Slice 18, Add 17,
Reshape 11, Div 10, Shape 9, Gather 9, Unsqueeze 7, Expand 6,
MaxPool 3, Transpose 3, Resize 2, Sub 2, Softmax 1   (opset 12)
```

- `Sigmoid`/`Softmax`：RKNN 支持（会量化，注意敏感层处理）
- `Resize` 2 个（上采样）：RKNN 支持，但**量化误差敏感**
- `Slice/Shape/Gather/Unsqueeze/Expand`：形状类算子，RKNN 通常可折叠；若报错用 `optimization_level=3` + 官方 YOLOv8 导出流程
- **DFL 的 `Mul/Div/Softmax/Concat`**：正是 RKNN 官方 YOLOv8 示例要处理的部分；
  如遇不支持，改用 `rknn_model_zoo/examples/yolov8` 的修改版导出（把 DFL 换成可导出形式）

## 4. 第五阶段：640 vs 960 精度对照（**实测，重要的否决结论**）

用同一 V3 权重**重新导出静态 640 图**（不是改输入尺寸），在同一 val 上评测：

| 分辨率 | Ball P/R/F1/AP50 | Hand P/R/F1/AP50 | Racket P/R/F1/AP50 |
| --- | --- | --- | --- |
| **960** | 0.823/**0.510**/0.630/0.492 | 0.691/0.558/0.618/0.504 | 0.760/0.756/0.758/0.689 |
| 640 | 0.417/**0.050**/0.089/0.054 | 0.660/0.473/0.551/0.430 | 0.636/0.438/0.519/0.392 |

**Ball Recall 从 0.510 崩到 0.050（−46 点）**。
原因很直接：val 的球中位 24.5 px，960 letterbox（scale 0.5）后 12.2 px，**640（scale 0.333）后只剩 8.2 px**，
远低于训练分布。

→ **640 路线否决**（除非为 640 重新训练，而本轮不训练）。
优先级因此固定为：**960 INT8 → 960 FP16**，不再考虑 640。

## 5. 已交付的转换与部署件（可直接在板端/Linux 跑）

| 文件 | 作用 |
| --- | --- |
| `convert_v3_to_rknn.py` | RKNN Toolkit2 转换：FP16 + INT8，含算子打印、多输出告警、`--eval-dir` 逐类精度自检 |
| `make_calib_list.py` | 生成 INT8 校准清单：**只用 train**，按 ball_only / ball_racket / hand_only / racket_other / empty 五桶各 60 张 |
| `calib/list.txt` | **已生成 300 张**（实测**0 张来自 val**） |
| `cpp/rknn_v3_detect.cpp` | RKNN C API 推理：GRAY8→Gray3→letterbox(双线性)→NPU→解码→类内 NMS→JSON；支持 `--core-mask auto/0/1/0_1`、`--bench N` 分阶段计时 |
| `cpp/CMakeLists.txt`、`build.sh` | 板端编译（链接 `librknnrt.so`） |
| `tools/verify_decode_pc.py` | **C++ 解码路径核验**（PC 端，无需板子） |

### C++ 解码路径核验结果

```
frames=40  identical/consistent=40  median IoU=1.000  min IoU=1.000
```

C++ 里的 letterbox / decode / NMS / 坐标恢复与 Python 参考**完全一致**。
⚠ 这只验证算法，**不是 RKNN 结果、也不是板端性能**。
（另：初版用最近邻缩放，实测会把小球框带偏，已改为双线性。）

## 6. 尚未完成（BLOCKED，如实列出）

| 项 | 状态 | 阻塞原因 |
| --- | --- | --- |
| FP16 RKNN 转换 | ❌ | 无 rknn-toolkit2（本机 Python 3.12 无 wheel） |
| INT8 RKNN 转换 | ❌ | 同上；校准清单已就绪 |
| INT8 精度评测（板端/模拟器） | ❌ | 无 RKNN |
| 板端 RKNN 加载 | ❌ | 板子不可达 |
| 单核/双核 FPS | ❌ | 同上 |
| NPU 纯推理时间 | ❌ | 同上 |
| 完整流水线 FPS | ❌ | 同上 |
| C++ 编译 | ❌ | 本机无 cmake/cl/g++；且需板端 aarch64 + librknnrt |
| OV9281 接入 | ❌ | 无相机、无板子 |
| RGA / FPGA 预处理 | ❌ | 未验证，仅提出方案 |

## 7. 下一步（有板子之后的最小验证路径）

```bash
# 1) 在 Linux x86_64 转换机（Python 3.8-3.10）上
python3 convert_v3_to_rknn.py \
  --onnx v3_960/pingpong_yolov8n_gray_3cls_v3_960_single_out.onnx \
  --calib calib/list.txt --out v3_960/rknn --target rk3576 \
  --eval-dir /path/to/pingpong_unified_3cls_v5     # 会自动打印逐类 P/R/F1

# 2) 板端
./build.sh
./build/rknn_v3_detect --model v3_960/rknn/*_int8.rknn --input frame.raw --width 1920 --height 1080
./build/rknn_v3_detect --model ... --input frame.raw --bench 500 --core-mask 0
./build/rknn_v3_detect --model ... --input frame.raw --bench 500 --core-mask 0_1
```

**看这三个数**：① INT8 的 ball recall 是否 ≥0.49；② NPU 纯推理毫秒；③ 双核是否真的比单核快。
