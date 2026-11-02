# QUANTIZATION_VALIDATION — FP32 / FP16 / INT8

日期：2026-11-03
目标模型：

- FP16：`artifacts/handoff/AFH03_FINAL_V3_FP16_FOR_CAPTAIN/v3_960_fp16_dfl_layout.rknn`
- INT8：`artifacts/rknn_deployment/v3_960_int8_v2/rknn/v3_960_int8_dfl_layout.rknn`
- ONNX：`.../v3_960_int8_v2/pingpong_v3_960_split_keepall.onnx`
  （以及实际 FP32 评测使用的 `.../AFH03_FINAL_V3_FP16_FOR_CAPTAIN/pingpong_yolov8n_gray_3cls_v3_960_960.onnx`）

## 1. 文件核验（实际 SHA256）

| 文件 | 大小 | SHA256 |
|---|---:|---|
| `v3_960_fp16_dfl_layout.rknn` | 13,038,908 | `1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b` |
| `v3_960_int8_dfl_layout.rknn` | 9,860,593 | `ccd13472d3fd70c63c5f1c6cb58fd9550aece1856bfc40113f5f5ab3fb0ef853` |
| `pingpong_v3_960_split_keepall.onnx` | 12,161,299 | `4e63796cb2c3aaea0b789533f5cae8d0f1a56a2e6d48bbe0270290e372ace3f8` |
| 原 V3 6 输出 ONNX（FP32 评测） | 12,161,114 | `b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba` |

文件名不能证明内容；以上为实际文件哈希。

## 2. RKNN 输出属性（从 `.rknn` 容器 header 实际解析）

解析工具：`tools/extract_rknn_meta.py`，只读，不推理。原始 JSON：

- `evidence/rknn_fp16_meta.json`
- `evidence/rknn_int8_meta.json`

### 2.1 实际输出数量与形状（两个模型相同）

**8 个输出**，不是模型卡写的 2 个：

| idx | name | shape | FP16 quant_dtype | INT8 quant_dtype | INT8 qtype |
|---:|---|---|---|---|---|
| 0 | `output0` | `[1,7,18900]` | float16 | float32 | asym |
| 1 | `onnx::Reshape_725` | `[1,64,18900]` | float16 | float32 | asym |
| 2 | `onnx::Sigmoid_769` | `[1,3,18900]` | float16 | float32 | asym |
| 3 | `onnx::Conv_607` | `[1,64,120,120]` | float16 | float32 | asym |
| 4 | `onnx::Conv_643` | `[1,128,60,60]` | float16 | float32 | asym |
| 5 | `onnx::Conv_679` | `[1,256,30,30]` | float16 | float32 | asym |
| 6 | `boxes` | `[1,4,18900]` | float16 | float32 | asym |
| 7 | `scores` | `[1,3,18900]` | float16 | float32 | asym |

输入：`images [1,3,960,960]`，float32；header mean 0、std 255。

### 2.2 scale / zero_point

- **FP16**：`quant_tab` 中无量化项（`quantized_tensors=0`），输出为 float16，不需要反量化。
- **INT8**：`quantized_tensors=9`，但 **8 个输出在 header 中 `scale` / `zero_point` 为空数组**，`quant_dtype` 为 **float32**，不是 int8。也就是说模型交付的 RKNN 输出已经是 **float32 反量化后的张量**；C++ 必须用 `want_float=1` 读取，不能把输出当 int8 再做 `(q-zp)*scale`。
- 不能在没有板端 `rknn_query(RKNN_QUERY_OUTPUT_ATTR)` 的情况下编造每个输出的 scale/zero_point；本轮**没有板子**，这一项为 **BLOCKED**。

> 任务要求“INT8 输出不能直接当浮点 logits 使用”。本模型实际情况相反：输出头本身是 float32；如果误按 int8 去读，会把浮点字节当量化整数，结果完全错误。

## 3. 生产 runtime 契约检查（实际静态验证）

`source/native/rk_runtime/c_rknn/runtime_session.cpp`：

```cpp
require(rknn_query(..., RKNN_QUERY_IN_OUT_NUM, &count, ...));
if (count.n_input != 1 || (count.n_output != 1 && count.n_output != 6))
  throw std::runtime_error("Expected one input and one primary output");
```

6 输出分支还要求：

```text
[1,64,120,120], [1,64,120,120], [1,64,60,60],
[1,64,60,60], [1,64,30,30], [1,64,30,30]  （class 头允许 1/3 通道）
```

即 **6 个 raw heads**。

实际模型：**8 outputs**，其中 `[1,7,18900]`、`[1,64,18900]`、`[1,3,18900]`、三个不同尺度 Conv、`boxes`、`scores`。因此：

```text
MODEL_RUNTIME_CONTRACT=FAIL
reason: runtime_session.cpp rejects this output count before any inference
```

证据：`evidence/model_contract_fp16.txt`、`evidence/model_contract_int8.txt`。

**结论：当前生产 C runtime 无法加载这两个 `*_dfl_layout.rknn` 模型。** 这是接口/模型契约问题，不是 FPS 问题，也不是 OpenCV 版本问题。

## 4. DFL 解码数学核验

实际 509 张 val 使用 DFL 张量：

```text
DFL: dfl.reshape(4,16,N)
softmax(16) -> expectation -> distances
stride 8/16/32 + grid center -> xyxy in 960
letterbox inverse -> original pixels
sigmoid(class logits) -> conf
threshold -> class-wise NMS
```

实际执行 `tools/eval_dfl_sim.py`（RKNN toolkit2 2.5.0 simulator，`target_platform=rk3588` 代理）与 `tools/eval_onnx_dfl.py`（FP32 ONNX Runtime）：

- FP32 与 FP16 的 509 张指标一致到 ±1.3 点；
- Ball / Racket 召回完全相同；
- 说明 DFL 的 softmax/期望/dist2bbox/letterbox 还原在 Python 参考实现中是正确的。

但 **生产 C++ `runtime_session` 的 6-head DFL 分支没有被任何可加载模型执行**；不能把 Python 参考结果写成 C++ 生产路径通过。

## 5. 509 张实测指标

固定 val：509 张，Ball 100 / Hand 1,172 / Racket 176 GT。
阈值：ball 0.20 / hand 0.25 / racket 0.25；IoU 0.5；NMS 0.5。

| 类别 | 模型 | P | R | F1 | TP | FP | FN |
|---|---|---:|---:|---:|---:|---:|---:|
| Ball | FP32 ONNX | 0.8226 | **0.5100** | 0.6296 | 51 | 11 | 49 |
| Ball | FP16 RKNN | 0.8095 | **0.5100** | 0.6258 | 51 | 12 | 49 |
| Ball | INT8 RKNN | 0.7833 | **0.4700** | 0.5875 | 47 | 13 | 53 |
| Hand | FP32 ONNX | 0.6913 | 0.5580 | 0.6176 | 654 | 292 | 518 |
| Hand | FP16 RKNN | 0.6917 | 0.5589 | **0.6182** | 655 | 292 | 517 |
| Hand | INT8 RKNN | 0.6726 | 0.5486 | **0.6043** | 643 | 313 | 529 |
| Racket | FP32 ONNX | 0.7600 | 0.7557 | 0.7578 | 133 | 42 | 43 |
| Racket | FP16 RKNN | 0.7644 | **0.7557** | 0.7600 | 133 | 41 | 43 |
| Racket | INT8 RKNN | 0.7557 | **0.7557** | 0.7557 | 133 | 43 | 43 |

原始 JSON：`evidence/fp32_onnx_509.json`、`fp16_rknn_509.json`、`int8_rknn_509.json`。

### 验收线

| 类别 | 门槛 | FP16 | INT8 |
|---|---|---|---|
| Ball Recall | ≥ 0.49 | **0.5100 PASS** | **0.4700 FAIL** |
| Hand F1 | ≥ 0.60 | **0.6182 PASS** | 0.6043 PASS |
| Racket Recall | ≥ 0.73 | **0.7557 PASS** | 0.7557 PASS |

**FP16 精度达标；INT8 Ball Recall 差 2 点，不得作为正式部署件。**

## 6. base_conf = 0.005 实际生效性

- `app/rk/model-config-int8.json` 实际值：`base_conf=0.005`，ball 0.02，hand 0.1，racket 0.1。
- 第一阶段代码链已通过 5 项静态/单测检查（`evidence/threshold_config_chain_test.txt`）。
- `threshold_policy_test` 实测：`.005` 保留 0.01 候选，拒绝 `-0.1/1.1/NaN`，`0/1` 边界正确（`evidence/threshold_policy_run.txt`）。
- **但是**：目标模型 8 输出无法被生产 runtime 加载，所以 `base_conf=0.005` 在当前部署链路上 **没有实际执行证据**。不能回答“已生效”。

结论：**阈值代码逻辑 PASS；部署链路生效性 FAIL/BLOCKED。**

## 7. 最终判定

| 项 | 状态 |
|---|---|
| FP32 509 指标 | **PASS（实际执行）** |
| FP16 509 指标 | **PASS（模拟器代理）** |
| INT8 509 指标 | **FAIL（Ball R 0.470）** |
| 输出数量/契约 | **FAIL（8 vs runtime 1/6）** |
| 输出 dtype | FP16 float16；INT8 float32（header） |
| scale/zero_point | **BLOCKED（header 无，需板端 query）** |
| DFL Python 参考数学 | **PASS** |
| 生产 C++ DFL 路径 | **NOT TESTED / 不可加载** |
| base_conf 实际生效 | **BLOCKED（模型无法加载）** |
