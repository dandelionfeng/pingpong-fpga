# PERFORMANCE_REPORT — AFH03 / RK3576J

日期：2026-11-03

## 1. 结论

**没有 RK3576J 实测 FPS。** 本轮没有 AFH03 实物、没有 `/dev/rknpu`、没有 `librknnrt.so`、ADB 设备为空；因此：

- NPU 纯推理：**BLOCKED**
- 单核/双核：**BLOCKED**
- 80/500 帧预热与正式测试：**NOT TESTED**
- 完整流水线 FPS：**BLOCKED**
- CPU/NPU 频率、负载、温度：**BLOCKED**

**不能把 PC 模拟器耗时或 PC ONNX CPU 耗时写成 RK3576J NPU FPS。** 本报告没有任何这样的替代数字。

## 2. 现有阶段计时（代码审计）

| 阶段 | 现有字段/位置 | 是否可直接用于验收 |
|---|---|---|
| 图像采集 | `camera_input_probe.cpp` 的 `setup_ms`/`elapsed_seconds`；`motion7_chain_bench` 的采集循环 | 仅采集/探针，不是完整流水线 |
| 预处理 | `runtime_session` 的 `input_layout_ms`；`motion7_chain_bench` 的 `input_decode_hash_resize` | 部分；letterbox 未单独计时 |
| NPU 前向 | `graph_timings["rknn_run_ms"]` / `rknn_inputs_set_ms` / `rknn_outputs_get_ms` | 有，但需板端 |
| DFL 解码 | `graph_timings["cpu_dfl_ms"]` | 有 |
| NMS | **无独立计时** | **缺失** |
| 结果传递 | `detector_backend` 的 `infer_ms` 包含推理+后处理 | 不是分阶段 |
| 完整流水线 | `motion7_chain_bench` 的 `main`、`input_to_detection_ms`、`c_infer` | 有框架，但无板端数据 |

`detector_backend_c_actual.cpp` 的诊断字段：

```text
infer_ms
graph_ms / rknn_graph_ms
```

`runtime_session.cpp` 的 `graph_timings` 键：

```text
input_layout_ms
rknn_inputs_set_ms
rknn_run_ms
rknn_outputs_get_ms
cpu_dfl_ms
<model_name>
```

### 缺口

1. 没有独立的 `nms_ms`。
2. 没有独立的 `letterbox_ms` / `gray3_ms`。
3. 没有把“采集→预处理→NPU→DFL→NMS→DetectionResult”写成统一 P50/P95。
4. 没有 50 帧预热 + 500 帧正式测试的板端脚本输出。

因此本轮不能声称“性能分析完成”；只能确认现有代码具备 NPU/DFL 计时入口，需要板端补测。

## 3. 板端测试步骤（待执行）

在 AFH03 上使用 **同一模型、同一分辨率、同一预处理**，每个配置至少：

```bash
# 预热 50 帧
./build/rknn_v3_detect --model /userdata/v3_960_fp16_dfl_layout.rknn \
  --input /userdata/frame_1920x1080.raw --width 1920 --height 1080 \
  --layout dfl --bench 50 --core-mask auto

# 正式 500 帧，单核/双核/自动分别执行
for M in auto 0 1 0_1; do
  ./build/rknn_v3_detect --model /userdata/v3_960_fp16_dfl_layout.rknn \
    --input /userdata/frame_1920x1080.raw --width 1920 --height 1080 \
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

**注意**：上述命令使用独立 `rknn_v3_detect_dfl` 工具，不是当前生产 `runtime_session`；生产 runtime 目前无法加载 8 输出模型（见 `QUANTIZATION_VALIDATION.md` 的契约 FAIL）。因此即使跑出数字，也不能直接等同于正式判罚链路。

## 4. 目标判定

| 目标 | 本轮 |
|---|---|
| 30 FPS 基础 | **NOT TESTED**（无板） |
| 50 FPS 优秀 | **NOT TESTED** |
| 90 FPS 挑战 | **NOT TESTED** |
| 不降低 960 输入/小球精度 | 约束已保留，未改分辨率/模型 |

## 5. 结论

**性能：BLOCKED。没有实测 FPS，不能交付 30/50/90 FPS 结论。** 需要真实 AFH03 + RKNN runtime + 可加载模型后才能测。
