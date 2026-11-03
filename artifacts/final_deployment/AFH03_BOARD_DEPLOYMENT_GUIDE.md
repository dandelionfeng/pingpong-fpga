# AFH03 / RK3576J BOARD DEPLOYMENT GUIDE

日期：2026-11-03
适用代码：`codex/final-afh03-deployment-20261103`
模型：FP16 `v3_960_fp16_dfl_layout.rknn`（SHA256 `1bcff6ff...cad0b`）

## 0. 先决条件

- AFH03 / RK3576J，Linux 板端。
- **RKNN Runtime ≥ 2.5.0**（8 输出 DFL 模型要求；2.3.0 会明确拒绝）。
- 与 runtime 匹配的 `rknn_api.h` 和 `librknnrt.so`。
- ARM64 OpenCV 4.13（或板端 sysroot）。
- 不要升级固件；不要用 2.3.0 强行加载 2.5 模型。

## 1. 上板前检查

```bash
uname -a
cat /proc/device-tree/compatible | tr -d '\0'
ls /dev/rknpu*
cat /sys/kernel/debug/rknpu/version
ldconfig -p | grep rknn
sha256sum /userdata/v3_960_fp16_dfl_layout.rknn
```

模型 SHA256 必须为：

```text
1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b
```

或直接运行：

```bash
sh tools/afh03_deployment_diagnostic.sh \
  --binary /userdata/build/motion7_chain \
  --model /userdata/v3_960_fp16_dfl_layout.rknn \
  --out /userdata/AFH03_DEPLOYMENT_DIAGNOSTIC.txt
```

## 2. 编译

```bash
cmake -S source/native -B build/rk -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=/opt/opencv4.13/lib/cmake/opencv4 \
  -DRKNN_INCLUDE_DIR=/opt/rknn/include \
  -DRKNN_RUNTIME_LIBRARY=/opt/rknn/lib/librknnrt.so
cmake --build build/rk --parallel 8
```

如果只验证 C_ACTUAL：

```bash
cmake -S source/native/base/software/pc_pipeline/modules/c_actual \
  -B build/c_actual -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=/opt/opencv4.13/lib/cmake/opencv4 \
  -DC_ACTUAL_ONNXRUNTIME_ROOT=/opt/onnxruntime
cmake --build build/c_actual --parallel 8
```

## 3. 8 输出模型加载

当前 `runtime_session.cpp` 会自动识别：

```text
[1,64,18900] DFL + 第一个 [1,3,18900] 分类 logits
```

前提：

- 1 个输入；
- 8 个输出；
- 输入 `[1,3,960,960]`；
- RKNN runtime ≥ 2.5.0。

启动后看日志：

```text
RKNN_PHYSICAL_CONTEXT model=... runtime=2.5.x ...
```

如果看到：

```text
8-output DFL model requires RKNN runtime >= 2.5.0; found 2.3.0
```

**停止**，升级 runtime 或按 2.3.0 重新转换模型；不要改代码绕过。

## 4. 配置

`app/rk/model-config-int8.json`：

```json
"diagnostic_thresholds": {
  "base_conf": 0.005,
  "ball": 0.02,
  "hand": 0.1,
  "racket": 0.1
}
```

- `base_conf` 进入 CPerceptionDetector → CPerceptionEngine → YoloDetector → OrtSession → RKNN candidate floor；
- 不要把 `.02` 硬编码回 runtime；
- 非法值（-0.1/1.1/NaN/Inf）应明确报错；
- Racket 仍由结果传递层过滤，不是模型删除第三类。

## 5. 单帧验证

```bash
./build/rknn_v3_detect --model /userdata/v3_960_fp16_dfl_layout.rknn \
  --input /userdata/frame_1920x1080.raw --width 1920 --height 1080 --layout dfl
```

检查：

1. 能打印 8 个输出且识别 DFL/class；
2. 框位置合理；
3. 三类分数（Ball/Hand/Racket）合理；
4. 不出现 NaN/Inf；
5. 不出现重复 sigmoid（分数不应整体被压到 0.5 附近）。

## 6. 509 张精度复测

使用固定 val 509，阈值/NMS/letterbox 与 PC 完全一致：

```bash
python3 tools/eval_dfl_sim.py ... --limit 509
python3 artifacts/final_deployment/tools/cpp_flat_509.py ...
```

板端应至少达到：

```text
Ball Recall >= 0.49
Hand F1 >= 0.60
Racket Recall >= 0.73（过滤前评估）
```

如果 Ball Recall 低于 0.49：先查 letterbox pad=114、是否重复 /255、模型 SHA、runtime 版本；不要用降低阈值掩盖漏检。

## 7. 性能

```bash
# 预热 50 + 正式 500；auto/0/1/0_1 各一次
./build/rknn_v3_detect --model ... --bench 50 --core-mask auto
./build/rknn_v3_detect --model ... --bench 500 --core-mask auto
./build/rknn_v3_detect --model ... --bench 500 --core-mask 0
./build/rknn_v3_detect --model ... --bench 500 --core-mask 1
./build/rknn_v3_detect --model ... --bench 500 --core-mask 0_1
```

记录：

- preprocess / NPU / DFL / NMS / result / total；
- Mean/P50/P95；
- NPU load、CPU、频率、温度。

**没有板端数据前，不要写 30/50/90 FPS 已达成。**

## 8. 回滚

- 保持原 2.3.0 runtime 和原 6 输出模型的板端镜像不变；
- 8 输出模型只作为新分支验证件；
- 失败时回退到原模型/原 runtime，不覆盖原 V3 交付 ZIP；
- 不要升级固件。

## 9. 交付给队长

- 代码：`codex/final-afh03-deployment-20261103`；
- 精度：FP16 509 通过；INT8 不通过（Ball R 0.470）；
- 模型：FP16 `v3_960_fp16_dfl_layout.rknn`；
- 仍需：真实 AFH03 + RKNN ≥2.5.0 板端加载和 FPS 报告。
