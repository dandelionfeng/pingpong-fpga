# BUILD_REPORT — AFH03 / RK3576J 部署验证

日期：2026-11-03
基线：`b4495fd4eb8cd798ba38105f64e2a51280e85647`
分支：`codex/afh03-deployment-20261103`
工作树：`D:\pp_fix_work`

## 1. 结论速览

| 项 | 状态 | 证据 |
|---|---|---|
| OpenCV 4.13.0 源码构建 | **PASS** | 4.13.0，core/imgproc/imgcodecs/videoio/calib3d/features2d |
| C_ACTUAL 使用 OpenCV 4.13 独立构建 | **PASS** | `libc_actual.a` 263,734 B |
| C_ACTUAL 动态链接检查 | **PASS** | `ldd` 显示 `libopencv_core.so.413`、`libonnxruntime.so.1` |
| Windows C_ACTUAL（3.4.1）回归 | **PASS** | configure/build rc=0 |
| 父级 `source/native` 完整构建 | **BLOCKED** | `rk_runtime/c_rknn/CMakeLists.txt` 要求 RKNN header + board runtime |
| ARM64 交叉编译 | **BLOCKED** | 无 `aarch64-linux-gnu-g++`、无 ARM64 OpenCV、无 `librknnrt.so` |
| 目标 RKNN 模型与生产 runtime 契约 | **FAIL** | 模型 8 输出；`runtime_session.cpp` 只接受 1 或 6 |

**不能把“C_ACTUAL 在 PC 上用 OpenCV 4.13 编译成功”写成“已在 RK3576J 上构建/运行成功”。**

## 2. OpenCV 4.13.0 构建（实际执行）

来源：`D:\pp_review_complete\runtime\board-dependencies\opencv-4.13.0-source.tar.gz`
环境：WSL2 Ubuntu 24.04，x86_64，GCC 13.3.0，CMake 3.28。

```bash
cmake -S /tmp/opencv413src -B /tmp/opencv413build \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/tmp/opencv413-install \
  -DBUILD_LIST=core,imgproc,imgcodecs,videoio,calib3d,features2d \
  -DBUILD_SHARED_LIBS=ON -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF \
  -DBUILD_EXAMPLES=OFF -DBUILD_opencv_apps=OFF -DBUILD_opencv_python3=OFF \
  -DWITH_IPP=OFF -DWITH_OPENCL=OFF -DWITH_FFMPEG=OFF -DWITH_GTK=OFF \
  -DWITH_JPEG=ON -DWITH_PNG=ON -DWITH_TIFF=OFF -DWITH_WEBP=OFF
cmake --build /tmp/opencv413build --parallel 8
cmake --install /tmp/opencv413build
```

实际输出：

```text
OpenCV 4.13.0
[100%] Built target opencv_calib3d
-- Installing...
OPENCV413_FULL_BUILD_OK
```

安装库：

```text
/tmp/opencv413-install/lib/libopencv_core.so.4.13.0
/tmp/opencv413-install/lib/libopencv_calib3d.so.4.13.0
/tmp/opencv413-install/lib/libopencv_features2d.so.4.13.0
```

## 3. C_ACTUAL / OpenCV 4.13（实际执行）

ONNX Runtime：Linux x64 1.20.1（官方 tarball），不是 Windows DLL。

```bash
cmake -S source/native/base/software/pc_pipeline/modules/c_actual \
  -B build/c_actual_opencv413 -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=/tmp/opencv413-install/lib/cmake/opencv4 \
  -DC_ACTUAL_ONNXRUNTIME_ROOT=/tmp/onnxruntime-linux-x64-1.20.1
cmake --build build/c_actual_opencv413 --parallel 8
```

实际输出：

```text
-- c_actual: using installed OpenCV 4.13.0 (/tmp/opencv413-install/lib/cmake/opencv4)
-- c_actual: ONNX Runtime root = /tmp/onnxruntime-linux-x64-1.20.1
[100%] Linking CXX static library libc_actual.a
[100%] Built target c_actual
C_ACTUAL_OPENCV413_BUILD_OK
```

产物：`build/c_actual_opencv413/libc_actual.a`，263,734 B。

动态链接探针（whole-archive 链接整个 c_actual）：

```text
libopencv_core.so.413 => /tmp/opencv413-install/lib/libopencv_core.so.413
libopencv_imgproc.so.413 => /tmp/opencv413-install/lib/libopencv_imgproc.so.413
libonnxruntime.so.1 => /tmp/onnxruntime-linux-x64-1.20.1/lib/libonnxruntime.so.1
```

### 3.1 构建系统兼容性修复

原 `CMakeLists.txt` 硬编码 `lib/onnxruntime.lib`，因此 Linux 下即使有 `libonnxruntime.so` 也直接 `FATAL_ERROR`。已改为按 `.lib` / `libonnxruntime.so` / `libonnxruntime.so.1` 顺序查找；Windows DLL 复制逻辑只在 `WIN32` 下执行。

这是构建系统修复，不改变推理算法；Windows 3.4.1 回归仍 rc=0。

## 4. Windows 回归（第一阶段环境）

```text
configure_rc=0
c_actual.vcxproj -> ...\Debug\c_actual.lib
build_rc=0
OpenCV 3.4.1
```

说明：Windows 本机仍只有 OpenCV 3.4.1 开发包；4.13 的 PASS 来自 WSL/Linux 构建。

## 5. 父级 `source/native` 构建

已用 OpenCV 4.13 + ONNX Runtime 1.20.1 配置父级，OpenCV 组件全部找到：

```text
Found OpenCV 4.13.0 components: core imgproc imgcodecs calib3d features2d
```

随后在 C 模块处停止：

```text
CMake Error at rk_runtime/c_rknn/CMakeLists.txt:4 (message):
  Matching private RKNN header and board runtime are required
```

原因：本机没有与模型匹配的 RKNN runtime `/usr/lib/librknnrt.so`，也没有 `/opt` 下的 board SDK。**不是 OpenCV 4.13 的问题。**

## 6. ARM64 交叉编译

检查结果：

```text
aarch64-linux-gnu-g++ : not found
WSL g++              : x86_64 only
rknn_api.h           : 有（runtime/board-dependencies/rknn_api.h）
librknnrt.so         : 无
OpenCV 4.13 ARM64    : 无
ADB devices          : 空
```

因此 **没有执行 AArch64 编译**；没有删除 NEON/RKNN 代码来“绕过”编译。需要：

1. `aarch64-linux-gnu-g++`（或 Rockchip 官方工具链）；
2. RKNN runtime 对应版本的 `rknn_api.h` 与 `librknnrt.so`；
3. ARM64 OpenCV 4.13（或板端 sysroot）；
4. 真实 AFH03 板子用于 `rknn_init`/NPU。

## 7. OpenCV API / 图像格式审计

C_ACTUAL 使用的 API：`cv::Mat`、`CV_8UC1/CV_8UC3/CV_32F`、`cvtColor`、`resize`、`split`、`Rect`、`Scalar`、`compare`、`findContours`、`boundingRect`、`mean`、`countNonZero`。这些在 OpenCV 3.x/4.x 均存在；4.13 构建成功是最强证据。

- `preprocess::grayToGray3` 强制 `CV_8UC1`，三通道值相同；BGR/RGB 顺序对灰度无影响。
- `preprocess::letterbox`：`INTER_LINEAR`，pad=114，`cv::Mat` `CV_8UC3`，与训练/评测一致。
- `yolo_detector_onnx.cpp`：BGR→RGB，NCHW，`/255`；RKNN 配置 mean=0、std=255，因此板端路径不能重复除 255。
- `runtime_session.cpp` 的原生图像路径要求 INT8/NHWC/dense；NEON 代码只在 ARM 编译，x86 未编译。
- 未发现 `IplImage`、`CV_LOAD_IMAGE_*`、`cv::xfeatures2d` 等 OpenCV 3.x 专属接口。

### 版本一致性

| 层 | 版本 |
|---|---|
| C++ 生产构建 | OpenCV **4.13.0** |
| 部署包 Python `cv2` | **5.0.0**（Windows runtime 与 WSL 均实测） |
| 第一阶段 Windows C++ | OpenCV 3.4.1（仅回归） |

**Python 5.0 与 C++ 4.13 不是同一版本**；虽然 `resize/cvtColor` 的像素语义通常一致，但本轮未做逐像素 Python-vs-C++ 对照，不能声称完全一致。需要在板端用同一预处理实现复核 letterbox/pad/归一化。

## 8. 状态汇总

| 项目 | 状态 |
|---|---|
| OpenCV 4.13 构建 | **PASS** |
| C_ACTUAL 独立构建 | **PASS** |
| 动态库链接 | **PASS（PC Linux）** |
| 父级完整构建 | **BLOCKED（RKNN）** |
| ARM64 真实编译 | **BLOCKED（工具链/SDK/板）** |
| RK3576J 实机 | **BLOCKED（无板）** |
