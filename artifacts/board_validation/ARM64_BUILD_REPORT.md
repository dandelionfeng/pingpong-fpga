# ARM64_BUILD_REPORT — RK3576J

日期：2026-11-03
分支：`codex/afh03-board-validation-20261103`

## 1. 结论

| 项 | 状态 |
|---|---|
| aarch64 交叉编译工具链 | **PASS**（Ubuntu GCC 13.3.0 cross） |
| ARM64 OpenCV 4.13 core/imgproc | **PASS** |
| `runtime_session.cpp` AArch64 编译 | **PASS** |
| `runtime_session` + OpenCV + RKNN 2.5 链接 | **PASS**（link harness） |
| `rknn_v3_detect_dfl` AArch64 可执行 | **PASS** |
| C_ACTUAL 五个源文件 AArch64 编译 | **PASS（对象级）** |
| C_ACTUAL 完整链接 | **BLOCKED**（缺 ARM64 ONNX Runtime） |
| 完整 `source/native` 板端链接 | **NOT TESTED / BLOCKED**（无板） |
| 板端运行 | **BLOCKED**（无 AFH03） |

**没有把 x86_64 结果伪装成 ARM64。所有 ARM 产物都用 `file` 验证为 `ELF 64-bit LSB ..., ARM aarch64`。**

## 2. 工具链

Ubuntu 24.04 的 cross 包（下载后解包到 `/tmp/arm64-root`，不安装系统）：

```text
g++-13-aarch64-linux-gnu     13.3.0-6ubuntu2~24.04.1cross1
gcc-13-aarch64-linux-gnu
binutils-aarch64-linux-gnu
libc6-dev-arm64-cross / libc6-arm64-cross
libstdc++-13-dev-arm64-cross / libstdc++6-arm64-cross
libgcc-13-dev-arm64-cross / libgcc-s1-arm64-cross
```

实际：

```text
aarch64-linux-gnu-g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
```

Hello 测试：

```text
ELF 64-bit LSB pie executable, ARM aarch64, interpreter /lib/ld-linux-aarch64.so.1
```

## 3. OpenCV 4.13 ARM64

源码：`runtime/board-dependencies/opencv-4.13.0-source.tar.gz`
构建：`core,imgproc`，shared，Release，`-march=armv8-a+simd`。

产物：

```text
libopencv_core.so.4.13.0    5,145,336 B
libopencv_imgproc.so.4.13.0 5,468,800 B
SHA256 core = bb789400e64095ba94586bad711f0d3bbf6b158f1a0cc8d52ac95ef05249dbf2
```

`file` 确认为 ARM aarch64。未构建 imgcodecs/videoio；C_ACTUAL 的板端 RKNN 链路不需要它们。

## 4. RKNN Runtime / Header

见 `BOARD_ENVIRONMENT_REPORT.md`：

```text
librknnrt.so  2.5.0  SHA256 4b6cc575...970c0
rknn_api.h          SHA256 2d4160cd...e666
```

## 5. `runtime_session` AArch64

```bash
aarch64-linux-gnu-g++ -std=c++17 -O2 -fPIC -march=armv8-a+simd \
  --sysroot=/tmp/arm64-root \
  -I/tmp/rknn-2.5.0 \
  -I/tmp/opencv413-arm64-install/include/opencv4 \
  -I source/native/rk_runtime/c_rknn \
  -I source/native/base/software/pc_pipeline/modules/c_actual/include \
  -c runtime_session.cpp -o runtime_session_arm64.o

file runtime_session_arm64.o
# ELF 64-bit LSB relocatable, ARM aarch64
```

链接 harness（`image_tensor.inc` + 空 main）证明所有符号可解析：

```bash
aarch64-linux-gnu-g++ ... runtime_session_arm64.o arm_runtime_link_main.o \
  -L/tmp/opencv413-arm64-install/lib -lopencv_core -lopencv_imgproc \
  -L/tmp/rknn-2.5.0 -lrknnrt -pthread -ldl -lm \
  -o motion7_rknn_runtime_arm64
```

`readelf -d`：

```text
NEEDED libopencv_core.so.413
NEEDED libopencv_imgproc.so.413
NEEDED librknnrt.so
NEEDED libstdc++.so.6 / libm.so.6 / libgcc_s.so.1 / libc.so.6
```

`file`：

```text
ELF 64-bit LSB pie executable, ARM aarch64
```

注意：这是 **link harness**，不是完整 `motion7_chain`；不能当正式可执行交付。

## 6. `rknn_v3_detect_dfl` AArch64 可执行

使用官方 2.5.0 header/runtime，实际构建：

```text
rknn_v3_detect_dfl_arm64  76 KB
ELF 64-bit LSB pie executable, ARM aarch64
SHA256 2508be71e354f8460a775fa92d9c8900181e3e10e9e5996a3f9f99f4fbd0ff38
```

该工具会打印：

- 模型 inputs/outputs 数量；
- 8 个输出的 dims/type/qnt/scale/zp/n_elems；
- 输入 shape/fmt/type；
- `rknn_mem_size`；
- 单帧推理 + DFL 检测结果。

已放在 `arm64/rknn_v3_detect_dfl_arm64`，**仅测试工具，不是正式判罚链路**。

## 7. C_ACTUAL AArch64 对象

五个源文件实际交叉编译为 ARM aarch64 `.o`：

```text
perception_engine.o
yolo_detector_onnx.o
balltrack_onnx.o
preprocessing.o
postprocessing.o
```

但 C_ACTUAL 需要 **ARM64 ONNX Runtime**，当前没有官方 ARM64 ONNX Runtime 开发包；完整链接 **BLOCKED**。板端正式链路使用 RKNN，不是 PC ONNX 路径。

## 8. 完整 `source/native`

未完成完整板端链接：

- 缺板端 `librknnrt.so` 安装/运行环境（本轮只在 host 链接）；
- 缺完整 ARM64 pipeline 依赖（nlohmann、pipeline 库、板端系统库）；
- 无 AFH03 板做运行验证。

**状态：BLOCKED，不宣称完整构建成功。**

## 9. 构建命令

见 `tools/aarch64-toolchain.cmake`、`BOARD_DEPLOYMENT_GUIDE.md`；工具链路径需按本机修改。
