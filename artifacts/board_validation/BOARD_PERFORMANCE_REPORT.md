# BOARD_PERFORMANCE_REPORT — AFH03 / RK3576J

日期：2026-11-03

## 1. 结论

**没有 AFH03 板端 FPS。** 没有实物、没有 `/dev/rknpu`、没有运行时环境；50 帧预热、500 帧正式测试、单核/双核对照均 **NOT TESTED**。

| 项 | 状态 |
|---|---|
| 50 帧预热 | **NOT TESTED** |
| 500 帧正式 | **NOT TESTED** |
| 单核 / 双核 / auto | **NOT TESTED** |
| Mean / P50 / P95 | **NOT TESTED** |
| Preprocess | **NOT TESTED** |
| NPU Forward | **BLOCKED** |
| DFL Decode | **NOT TESTED（板端）** |
| NMS | **NOT TESTED** |
| Result Transfer | **NOT TESTED** |
| Total Latency | **NOT TESTED** |
| 30 / 50 / 90 FPS | **NOT TESTED** |

**不能用 PC CPU、RK3588 模拟器或 ARM64 交叉编译结果代替 RK3576 板端 FPS。**

## 2. 本轮完成的性能准备

- 官方 Runtime 2.5.0 + ARM64 OpenCV 4.13 + RKNN 2.5 的 AArch64 链接通过；
- `rknn_v3_detect_dfl` AArch64 可执行已构建，支持 `--bench` 和 `--core-mask`；
- 8 输出适配使用 `want_float=1`，不手工重复反量化；
- 复用 `RknnSharedContext`，不重复 `rknn_init`；
- 输入/输出 buffer 生命周期由原有 context 管理。

仍未做：

- 8 输出一次取 8 个 tensor 的额外拷贝开销未实测；
- `want_float=1` 与原生输出读取的性能差未实测；
- NMS 未单独计时/向量化；
- RGA 预处理未接入；
- 双核是否真正加速未测。

## 3. 板端测试命令

```bash
export LD_LIBRARY_PATH=/userdata/pingpong/rknn-2.5.0/lib:$LD_LIBRARY_PATH

# 预热 50
./rknn_v3_detect_dfl --model model/v3_960_fp16_dfl_layout.rknn \
  --input frame_1920x1080.raw --width 1920 --height 1080 \
  --layout dfl --bench 50 --core-mask auto

# 正式 500，四种 core mask
for M in auto 0 1 0_1; do
  ./rknn_v3_detect_dfl --model model/v3_960_fp16_dfl_layout.rknn \
    --input frame_1920x1080.raw --width 1920 --height 1080 \
    --layout dfl --bench 500 --core-mask "$M"
done
```

同时采集：

```bash
cat /sys/kernel/debug/rknpu/load
cat /sys/class/devfreq/*/cur_freq
top -b -n1 | head -15
cat /sys/class/thermal/thermal_zone*/temp
```

## 4. 计时口径

`rknn_v3_detect_dfl` 输出：

```text
pre_ms / npu_ms / post_ms / total_mean_ms / total_p50_ms / total_p95_ms
```

正式 `runtime_session` 内部：

```text
input_layout_ms
rknn_inputs_set_ms
rknn_run_ms
rknn_outputs_get_ms
cpu_dfl_ms
```

必须分开报告，不能把 `pre_ms + npu_ms + post_ms` 直接当采集到结果的完整流水线。

## 5. 状态

**性能：BLOCKED。没有实测 FPS；不能声称达到 30/50/90 FPS。** 先完成 2.5.0 板端加载和精度，再测性能。
