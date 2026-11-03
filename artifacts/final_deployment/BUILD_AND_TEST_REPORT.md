# BUILD_AND_TEST_REPORT — final AFH03 integration

日期：2026-11-03
分支：`codex/final-afh03-deployment-20261103`

## 1. 构建环境

| 项 | 值 |
|---|---|
| Windows | MSVC 19.44, Visual Studio 2022 |
| Linux | WSL2 Ubuntu 24.04, GCC 13.3.0, CMake 3.28 |
| OpenCV | **4.13.0**（源码构建，Linux x86_64） |
| ONNX Runtime | 1.20.1（Windows DLL / Linux .so） |
| RKNN Toolkit2 | 2.5.0（WSL，模拟器） |
| 目标板 | AFH03 / RK3576J：**不可达** |

## 2. 实际构建结果

### 2.1 OpenCV 4.13.0：PASS

```bash
cmake -S /tmp/opencv413src -B /tmp/opencv413build \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/tmp/opencv413-install \
  -DBUILD_LIST=core,imgproc,imgcodecs,videoio,calib3d,features2d \
  -DBUILD_SHARED_LIBS=ON ...
cmake --build ... --parallel 8
cmake --install ...
```

结果：`OPENCV413_FULL_BUILD_OK`，`libopencv_core.so.4.13.0`。

### 2.2 C_ACTUAL + OpenCV 4.13：PASS

```bash
cmake -S source/native/base/software/pc_pipeline/modules/c_actual \
  -B build/c_actual_opencv413 -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=/tmp/opencv413-install/lib/cmake/opencv4 \
  -DC_ACTUAL_ONNXRUNTIME_ROOT=/tmp/onnxruntime-linux-x64-1.20.1
cmake --build build/c_actual_opencv413 --parallel 8
```

结果：`C_ACTUAL_OPENCV413_BUILD_OK`，`libc_actual.a` 263,734 B。

动态链接：

```text
libopencv_core.so.413
libopencv_imgproc.so.413
libonnxruntime.so.1
```

### 2.3 Windows C_ACTUAL（3.4.1）回归：PASS

```text
configure_rc=0
build_rc=0
```

### 2.4 父级 source/native：BLOCKED

OpenCV 4.13 组件全部找到，但在 C 模块停止：

```text
CMake Error at rk_runtime/c_rknn/CMakeLists.txt:4:
  Matching private RKNN header and board runtime are required
```

缺少 board 的 `librknnrt.so`。不是 OpenCV 问题。

### 2.5 ARM64：BLOCKED

```text
aarch64-linux-gnu-g++ : not found
librknnrt.so          : not found
ARM64 OpenCV 4.13     : not found
ADB devices           : empty
```

没有删除 NEON/RKNN 代码；只是缺少工具链/SDK/板。

## 3. C++ 代码新增与验证

### 3.1 8 输出适配

新增：

- `output_layout_policy.hpp`：1/6/8 输出模式；
- `dfl_flat_decoder.hpp`：8 输出 DFL 解码；
- `runtime_session.cpp`：`kFlatDfl` 分支；
- `tests/flat_dfl_test.cpp`。

### 3.2 单元测试：PASS

MSVC 与 g++ 均实际执行：

```text
flat_dfl_test: PASS (8-output layout, DFL, single sigmoid, base_conf 0/1, release-safe decode)
```

覆盖：

- 1/6/8 输出模式；
- 8 输出 layout 识别（DFL idx 1，class idx 2）；
- 非法 7/重复 64 通道拒绝；
- DFL synthetic 数值；
- 单次 sigmoid；
- base_conf 0/1；
- skip_all。

日志：`evidence/flat_dfl_compile.txt`、`flat_dfl_run.txt`。

### 3.3 `runtime_session.cpp` 语法检查：PASS

使用 host-only ARM Neon stub（**不是生产后端**）：

```text
g++ -std=c++17 -fsyntax-only ... runtime_session.cpp
rc=0
```

日志：`evidence/runtime_session_syntax.log`（0 字节表示无错误）。

### 3.4 C++ 509 张解码回归：PASS

`tools/flat_decoder_shared.cpp` 编译为 host `.so`，`tools/cpp_flat_509.py` 用 ctypes 调用，输入 509 张 ONNX 的 DFL/logits：

```text
cpp_flat_dfl_509
Ball   P=0.8226 R=0.5100 F1=0.6296 AP50=0.4870
Hand   P=0.6913 R=0.5580 F1=0.6176 AP50=0.5063
Racket P=0.7600 R=0.7557 F1=0.7578 AP50=0.6914
per_image=509
```

单帧 C++/Python 误差：score 5.96e-08，中心/宽高 9.16e-05 px。

详见 `MODEL_ACCURACY_REGRESSION.md`。

## 4. 回归测试汇总

| 测试 | 结果 | 证据 |
|---|---|---|
| OpenCV 4.13 build | PASS | `evidence/opencv413_*` |
| C_ACTUAL 4.13 build | PASS | `evidence/c_actual_opencv413_*` |
| Windows C_ACTUAL | PASS | 命令输出 |
| 1/6/8 mode test | PASS | `flat_dfl_run.txt` |
| flat DFL decode test | PASS | `flat_dfl_run.txt` |
| runtime syntax check | PASS | `runtime_session_syntax.log` |
| C++ 509 decode | PASS | `cpp_flat_509.json` |
| FP32 ONNX 509 | PASS | `fp32_onnx_509.json` |
| FP16 simulator 509 | PASS | `fp16_rknn_509.json` |
| INT8 simulator 509 | FAIL (Ball R) | `int8_rknn_509.json` |
| Python unit tests (phase 1/2) | 19/19 PASS | `python_tests_all.txt` |
| `check_repo.py` | PASS | `check_repo.txt` |
| RKNN actual load | BLOCKED | no board/runtime |
| ARM64 compile | BLOCKED | no toolchain |
| NPU FPS | BLOCKED | no board |

## 5. 独立构建命令（给下一个执行人）

```bash
# C_ACTUAL only, Linux
cmake -S source/native/base/software/pc_pipeline/modules/c_actual \
  -B build/c_actual_opencv413 -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=$OPENCV_DIR \
  -DC_ACTUAL_ONNXRUNTIME_ROOT=$ONNXRUNTIME_ROOT
cmake --build build/c_actual_opencv413 --parallel 8

# full native, requires board RKNN runtime and ARM64 OpenCV
cmake -S source/native -B build/rk -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=$OPENCV_ARM64_DIR \
  -DRKNN_INCLUDE_DIR=$RKNN_SDK/include \
  -DRKNN_RUNTIME_LIBRARY=$RKNN_SDK/lib/librknnrt.so
cmake --build build/rk --parallel 8
```

## 6. 未完成

- 8 输出模型在 RK3576J 上实际 `rknn_init`/NPU 推理：**BLOCKED**。
- ARM64 真实编译：**BLOCKED**。
- C++ NMS 的独立数值单测：**NOT TESTED**（沿用现有 `YoloDetector` 路径）。
- 父级完整构建：**BLOCKED**（RKNN runtime）。
