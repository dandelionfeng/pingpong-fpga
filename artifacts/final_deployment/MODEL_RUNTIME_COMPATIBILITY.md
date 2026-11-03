# MODEL_RUNTIME_COMPATIBILITY — V3 RKNN / RK3576J

日期：2026-11-03
实现分支：`codex/final-afh03-deployment-20261103`

## 1. 选择的路线

**路线 A：修改生产 C++ Runtime，新增 8 输出 DFL 模式。**

原因：

- 现有 V3 权重、960 输入、三分类均不改；
- 不重新训练；
- 8 输出模型是当前实际交付文件；
- 路线 B（重新导出 6-head）需要 RKNN Toolkit 重新转换和板上验证，当前无板、无匹配 runtime，无法在本轮闭环。

## 2. 实际模型输出（以 `.rknn` header 为准）

| idx | name | shape | FP16 | INT8 |
|---:|---|---|---|---|
| 0 | `output0` | [1,7,18900] | float16 | float32/asym |
| 1 | `onnx::Reshape_725` | [1,64,18900] | float16 | float32/asym |
| 2 | `onnx::Sigmoid_769` | [1,3,18900] | float16 | float32/asym |
| 3 | `onnx::Conv_607` | [1,64,120,120] | float16 | float32/asym |
| 4 | `onnx::Conv_643` | [1,128,60,60] | float16 | float32/asym |
| 5 | `onnx::Conv_679` | [1,256,30,30] | float16 | float32/asym |
| 6 | `boxes` | [1,4,18900] | float16 | float32/asym |
| 7 | `scores` | [1,3,18900] | float16 | float32/asym |

模型哈希：

```text
FP16 1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b
INT8 ccd13472d3fd70c63c5f1c6cb58fd9550aece1856bfc40113f5f5ab3fb0ef853
```

## 3. 代码如何识别 8 输出

新增：

- `output_layout_policy.hpp`：1 / 6 / 8 输出模式选择；
- `dfl_flat_decoder.hpp`：8 输出 DFL 解码；
- `runtime_session.cpp`：`OutputMode::kFlatDfl` 分支。

识别规则：

1. 输出总数为 8；
2. 必须存在 `[1,64,18900]` 的 DFL 张量；
3. 必须存在 `[1,3,18900]` 的分类张量；
4. 选择**索引最小的 3 通道张量**（index 2，`onnx::Sigmoid_769`），不选 index 7 的 `scores`；
5. 忽略 `output0`（混合框/分数）、`boxes`、三个中间 Conv；
6. 使用 DFL 做 softmax(16)→期望→dist2bbox；
7. 分类 logits 只做 **一次 sigmoid**；
8. 输出 `[1,4+3,18900]`，保持原 `YoloDetector` 契约。

**为什么选第一个 3 通道：** Python 509 参考实现就是取第一个 `[1,3,N]` 并做一次 sigmoid，结果与 FP32 基线一致；index 7 的 `scores` 已经是 sigmoid 后结果，选它会二次 sigmoid。

## 4. 输出 dtype / 反量化

8 输出模式统一：

```cpp
results[i].want_float = 1;
rknn_outputs_get(ctx, 8, results, nullptr);
```

因此：

- FP16：runtime 将 float16 转 float32，只转换一次；
- FP32：原样读取；
- INT8：若 runtime 内部为 int8，`want_float=1` 由 runtime 按模型 scale/zp 反量化；
- **不再手工执行 `(q-zp)*scale`**，避免对已经 float32 的 INT8 输出重复反量化。

模型 header 显示 INT8 8 个输出 `quant_dtype=float32`，这进一步说明手工按 int8 读会错。

## 5. Runtime 版本策略

代码不再无条件要求 2.3.0：

- 1/6 输出：接受 **2.3.0** 或 **≥2.5.0**；
- 8 输出：要求 **≥2.5.0**；
- 2.3.0 加载 8 输出模型会明确报错：

```text
8-output DFL model requires RKNN runtime >= 2.5.0; found 2.3.0.
Do not bypass this check; upgrade the board runtime.
```

这不是删除版本检查，而是把模型/运行时的真实要求写清楚。当前没有 2.5.0 runtime/板子，所以 **实际加载 BLOCKED**；在有 2.5.0 runtime 的板上才能验证。

## 6. 1 / 6 / 8 输出回归

`tests/flat_dfl_test.cpp` 实际执行：

```text
select_output_mode(1) -> kSingle
select_output_mode(6) -> kRawHeads
select_output_mode(8) -> kFlatDfl
select_output_mode(2) -> reject
8-output layout -> DFL index=1, class index=2, anchors=18900
DFL synthetic -> center/wh/scores correct
base_conf=0/1 -> correct
```

日志：`evidence/flat_dfl_run.txt`。

## 7. 内存 / 生命周期

8 输出分支：

```cpp
rknn_output results[8]{};
...
require(rknn_outputs_get(context, 8, results, nullptr), "get eight DFL outputs");
struct FlatRelease { ... ~FlatRelease(){ rknn_outputs_release(context, 8, p); } } release{...};
```

- 输出在作用域结束时释放；
- 输入/模型 context 继续由原有 `RknnSharedContext` 管理；
- 没有新增 session 泄漏；
- 没有把 output 缓冲交给调用者。

## 8. 兼容性结论

| 项 | 状态 |
|---|---|
| 8 输出代码适配 | **PASS（单元测试 + C++ 509 解码）** |
| 1/6 输出模式保留 | **PASS（代码路径保留，模式单测）** |
| 8 输出在 2.3 runtime 加载 | **FAIL（明确拒绝，符合版本要求）** |
| 8 输出在 2.5 runtime 加载 | **NOT TESTED（无 runtime/板）** |
| 实际 NPU 输出属性 query | **BLOCKED（无板）** |
| FP16/FP32/INT8 手工重复反量化 | **已避免（want_float=1）** |
| 重复 sigmoid | **已避免（只选第一个 3 通道并 sigmoid 一次）** |
| 模型/权重修改 | **无** |
