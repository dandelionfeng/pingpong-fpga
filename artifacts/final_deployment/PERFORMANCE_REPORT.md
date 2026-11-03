# PERFORMANCE_REPORT — final AFH03 integration

日期：2026-11-03

## 1. 结论

**没有 RK3576J 实测 FPS。** 没有 AFH03 实物、没有 `/dev/rknpu`、没有 `librknnrt.so`、ADB 设备为空；不能用 PC/模拟器数字替代。

| 指标 | 状态 |
|---|---|
| Preprocess | NOT TESTED（无板） |
| NPU Forward | BLOCKED（无板/runtime） |
| DFL Decode | 只在 PC 上验证正确性；延迟 NOT TESTED |
| NMS | NOT TESTED（现有路径） |
| Result Transfer | NOT TESTED |
| Total Latency | NOT TESTED |
| 30 FPS | NOT TESTED |
| 50 FPS | NOT TESTED |
| 90 FPS | NOT TESTED |

## 2. 本轮已做的性能相关代码工作

### 2.1 8 输出适配

- 不再只获取 1 个输出；8 输出模式获取 8 个 `rknn_output`，`want_float=1`；
- 只解码 DFL（64 通道）和第一个 3 通道 logits，忽略 6 个无关/重复张量；
- 避免额外 sigmoid / 手工反量化；
- 输出 7×18900 的 `[1,7,N]`，复用现有 `YoloDetector` NMS。

### 2.2 生命周期

- `RknnSharedContext` 缓存 model context，避免每次 `rknn_init`；
- 8 输出 `FlatRelease` 保证 `rknn_outputs_release(ctx,8,...)`；
- 输入 buffer 复用原有 `quant_input`/`native_input`；
- 没有新增每次推理的 session。

### 2.3 尚未优化/验证

- 8 输出模式一次取 8 个 tensor，理论上比只取 2 个多拷贝；需要板端测量后再决定是否改用 `rknn_outputs_get` 的按索引方案；
- `want_float=1` 可能带来 runtime 反量化/转换成本；需与 INT8 原生输出比较；
- NMS 仍用现有 `YoloDetector` 类内 NMS，未做 C++ 侧向量化；
- RGA resize / GRAY8→Gray3 是否可用：**未实现、未验证**；
- 单核/双核 `rknn_set_core_mask` 路径保留，但没有板端双核数据。

## 3. 计时入口（现有）

`runtime_session.cpp`：

```text
input_layout_ms
rknn_inputs_set_ms
rknn_run_ms
rknn_outputs_get_ms
cpu_dfl_ms
<model_name>
flat_dfl_layout (标记)
```

`detector_backend`：

```text
infer_ms
rknn_graph_ms
```

缺口：

- 无独立 `nms_ms`；
- 无独立 `letterbox_ms`；
- 无采集→结果统一 P50/P95；
- 无 50 预热 + 500 正式帧的板端报告。

## 4. 板端测量步骤（必须真实执行）

```bash
# 预热 50
./build/rknn_v3_detect --model /userdata/v3_960_fp16_dfl_layout.rknn \
  --input /userdata/frame_1920x1080.raw --width 1920 --height 1080 \
  --layout dfl --bench 50 --core-mask auto

# 正式 500，auto/0/1/0_1
for M in auto 0 1 0_1; do
  ./build/rknn_v3_detect --model /userdata/v3_960_fp16_dfl_layout.rknn \
    --input /userdata/frame_1920x1080.raw --width 1920 --height 1080 \
    --layout dfl --bench 500 --core-mask "$M"
done

cat /sys/kernel/debug/rknpu/load
cat /sys/class/devfreq/*/cur_freq
```

**注意**：`rknn_v3_detect` 是独立 DFL 工具；正式生产 runtime 的 8 输出路径还要在板端用实际 C++ 可执行文件测，不能把独立工具结果直接当成正式流水线。

## 5. 结论

**性能：BLOCKED。没有 FPS 数字，不能声称 30/50/90 FPS。** 先保证模型契约和 runtime 版本正确，再测性能；不能用降低 960 分辨率或牺牲 Ball 召回换 FPS。
