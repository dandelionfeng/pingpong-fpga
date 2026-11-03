# BOARD_DEPLOYMENT_GUIDE — AFH03 / RK3576J

日期：2026-11-03
适用分支：`codex/afh03-board-validation-20261103`
模型：FP16 `v3_960_fp16_dfl_layout.rknn`（SHA256 `1bcff6ff...cad0b`）

## 1. 不要覆盖系统 Runtime

目标组合：

```text
Toolkit2 2.5.0  ->  Runtime 2.5.0  ->  8 输出 FP16 模型
```

板端可能已有 2.3.x。请把 2.5.0 放在应用目录：

```bash
mkdir -p /userdata/pingpong/rknn-2.5.0/lib
# 从 PC 复制（或用 fetch 脚本）
export LD_LIBRARY_PATH=/userdata/pingpong/rknn-2.5.0/lib:$LD_LIBRARY_PATH
```

不要直接 `cp` 覆盖 `/usr/lib/librknnrt.so`；也不要升级固件。若板厂要求系统库，先备份并取得批准。

## 2. 获取/核验官方 2.5.0

PC 侧：

```bash
sh tools/fetch_rknn_2.5.0.sh ./rknn-2.5.0
```

必须得到：

```text
librknnrt.so  SHA256 4b6cc575...970c0
rknn_api.h    SHA256 2d4160cd...e666
librknnrt version: 2.5.0
```

模型 SHA：

```bash
sha256sum /userdata/pingpong/models/v3_960_fp16_dfl_layout.rknn
# 1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b
```

## 3. 编译

```bash
# 工具链前缀按实际修改
export CROSS=/opt/gcc-aarch64/bin/aarch64-linux-gnu-
cmake -S source/native -B build/rk-arm64 \
  -DCMAKE_TOOLCHAIN_FILE=tools/aarch64-toolchain.cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=/opt/opencv4.13-arm64/lib/cmake/opencv4 \
  -DRKNN_INCLUDE_DIR=/opt/rknn-2.5.0 \
  -DRKNN_RUNTIME_LIBRARY=/opt/rknn-2.5.0/librknnrt.so
cmake --build build/rk-arm64 --parallel 8
```

本阶段已在 host 验证：

- `runtime_session.cpp` AArch64 编译 + OpenCV 4.13 + RKNN 2.5 链接；
- `rknn_v3_detect_dfl` AArch64 可执行；
- C_ACTUAL 五个源文件 AArch64 对象；
- **完整 `source/native` 板端链接/运行 BLOCKED**（无板/完整 ARM64 依赖）。

## 4. 板端诊断

```bash
sh tools/afh03_deployment_diagnostic.sh \
  --binary /userdata/pingpong/rknn_v3_detect_dfl \
  --model /userdata/pingpong/models/v3_960_fp16_dfl_layout.rknn \
  --out /userdata/pingpong/AFH03_DEPLOYMENT_DIAGNOSTIC.txt
```

检查：

- `compatible` 包含 `rk3576`；
- `/sys/kernel/debug/rknpu/version` 可读；
- `librknnrt` 为 2.5.0；
- 模型 SHA 正确；
- 8 输出 / `[1,64,18900]` / `[1,3,18900]`；
- memory query 成功；
- 单帧推理返回 0。

## 5. 单帧模型探针

```bash
export LD_LIBRARY_PATH=/userdata/pingpong/rknn-2.5.0/lib:$LD_LIBRARY_PATH
./rknn_v3_detect_dfl \
  --model /userdata/pingpong/models/v3_960_fp16_dfl_layout.rknn \
  --input /userdata/pingpong/frame_1920x1080.raw \
  --width 1920 --height 1080 --layout dfl --core-mask auto
```

必须看到：

```text
outputs=8
out[1] ... dims=[1,64,18900] ...
out[2] ... dims=[1,3,18900] ...
memory weight_bytes=...
detections
```

注意：`rknn_v3_detect_dfl` 是测试工具，不是正式判罚链路；正式 `runtime_session` 也要单独加载验证。

## 6. 精度

509 张固定 val，阈值/NMS/letterbox 与 PC 一致：

```text
Ball Recall >= 0.49
Hand F1 >= 0.60
Racket Recall >= 0.73（过滤前）
```

板端 509 张是 **本轮未执行**，见 `BOARD_ACCURACY_REPORT.md`。

## 7. 性能

```bash
# 50 预热 + 500 正式；分别 auto/0/1/0_1
./rknn_v3_detect_dfl --model ... --input frame.raw --width 1920 --height 1080 \
  --layout dfl --bench 50 --core-mask auto
./rknn_v3_detect_dfl --model ... --input frame.raw --width 1920 --height 1080 \
  --layout dfl --bench 500 --core-mask 0
./rknn_v3_detect_dfl --model ... --input frame.raw --width 1920 --height 1080 \
  --layout dfl --bench 500 --core-mask 1
./rknn_v3_detect_dfl --model ... --input frame.raw --width 1920 --height 1080 \
  --layout dfl --bench 500 --core-mask 0_1
```

记录 pre/NPU/post/total 的 Mean/P50/P95，NPU load、频率、温度。

**没有板端数据前，不要写 30/50/90 FPS 已达成。**

## 8. 回滚

- 保留原 2.3.x runtime 和原模型；
- 2.5.0 只通过 `LD_LIBRARY_PATH` 使用；
- 不改固件、不覆盖正式发布 ZIP；
- 失败时删除应用目录的 2.5.0，恢复原环境。
