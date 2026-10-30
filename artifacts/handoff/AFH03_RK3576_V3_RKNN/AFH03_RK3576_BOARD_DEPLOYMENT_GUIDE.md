# AFH03 / RK3576J 板端部署指南（V3 三分类 YOLO）

版本：2026-10-30　适用：`pingpong_yolov8n_gray_3cls_v3_960_single_out.onnx`
状态：**本文所有板端步骤均未在本机执行**（无 AFH03 实物、无 RKNN 文件）。
文中命令按 Rockchip 官方流程编写，**不含任何真实 IP、用户名或密码**——凡涉及这些值的地方都用
`<占位符>`，请按你们实际网络与登录信息填写。

---

## 0. 三个环境的职责划分（先搞清这个，能省半天）

| 环境 | 系统 | 装什么 | 干什么 |
| --- | --- | --- | --- |
| **转换端** | **Linux x86_64**（Ubuntu 20.04/22.04/24.04 或 Docker） | `rknn-toolkit2`（Python 包） | ONNX → `.rknn`（FP16 / INT8） |
| 板端 | AFH03 上的 Linux **aarch64** | `librknnrt.so` + `rknn_api.h` | 加载 `.rknn`、跑 NPU |
| 板端（可选） | 同上 | `rknn-toolkit-lite2` | 用 Python 快速验证，不用写 C++ |

> ⚠ **Windows 上装不了 rknn-toolkit2**。实测：PyPI 上 `rknn-toolkit2` 的 wheel 全部是
> **manylinux**（`manylinux_2_17_x86_64` / `aarch64`），**没有任何 Windows wheel**
> （`win_amd64` 数量为 0）。所以本机 Windows + Python 3.12 装不上，**不是 Python 版本的问题**——
> Python 3.12 是官方支持的（2.2.0 就有 `cp312-manylinux_x86_64` wheel）。
> 解决路径：WSL2 / Docker / 一台 Linux 机器。

---

## 1. SDK 版本对应关系

| 层 | 组件 | 获取方式 | 说明 |
| --- | --- | --- | --- |
| 转换 | `rknn-toolkit2` | `pip install rknn-toolkit2`（Linux） | 官方最新 **v2.5.0**；Python 3.6–3.12 |
| 板端运行库 | `librknnrt.so` + `rknn_api.h` | `rknn-toolkit2` 仓库的 `rknpu2/runtime/Linux/librknn_api/` | 与 toolkit **同版本发布** |
| 内核驱动 | `rknpu` 驱动 | 板厂固件自带（`/dev/rknpu`、`/sys/kernel/debug/rknpu/`） | 一般随固件，不单独升级 |
| 板端 Python（可选） | `rknn-toolkit-lite2` | `pip install rknn-toolkit-lite2`（板端 aarch64） | 与运行库同版本 |

**兼容规则（官方语义）**：`.rknn` 模型里带版本号，**板端 runtime 必须 ≥ 转换端 toolkit 版本**。
例如用 toolkit 2.3.0 转的模型，板端 `librknnrt.so` 必须 ≥ 2.3.0，否则 `rknn_init` 直接报版本错误。

**本项目的建议组合（保守、可复现）**：

| 角色 | 版本 |
| --- | --- |
| 转换端 | `rknn-toolkit2==2.3.0`（或与板厂固件同版本；**优先选与板端 runtime 完全一致**） |
| 板端 runtime | 与转换端**完全一致**（从同一个 toolkit 包的 `rknpu2/runtime/` 取 `librknnrt.so`） |
| 板端 Python | `rknn-toolkit-lite2==2.3.0`（若用 Python 验证） |

> 拿不准时：**先查板端 `librknnrt.so` 版本，再挑同版本 toolkit**，比反过来省事。

---

## 2. 连接 AFH03（不写死任何 IP/账号）

### 2.1 串口（最稳，第一次必用）
1. Type-C/USB 转串口接板子的 **DEBUG UART**；
2. Windows 设备管理器看新增的 COM 口（如 `COMx`）；
3. 用 PuTTY / MobaXterm / `tio` 连接：**波特率 1500000**（Rockchip 常见；若乱码依次试 115200）；
4. 上电，看到 U-Boot 与内核日志即成功；登录账号密码见**板厂提供的固件说明**（本文不提供）。

### 2.2 网络（跑了服务再用）
```bash
# 在串口里查板子自己的 IP（不要猜）
ip -4 addr show | grep inet
# 或
hostname -I
```
拿到 IP 后，从 PC：
```bash
ssh <用户名>@<板子IP>
```

### 2.3 ADB（若镜像开了 adbd）
```bash
adb devices          # 应看到 <serial>  device
adb shell            # 进板子
adb push file /tmp/  # 传文件
```

### 2.4 直连网线（无路由器时）
把 PC 网卡设为 `192.168.1.2/24` 之类的静态地址，板子设为同网段另一地址（**具体地址以你们自己的规划为准**），
然后按 2.2 查板子 IP。

---

## 3. 板端环境检查（逐条执行并记录输出）

```bash
# 1) 芯片与系统
uname -a
cat /etc/os-release | head -3
cat /proc/device-tree/compatible; echo          # 应含 rockchip,rk3576
cat /proc/cpuinfo | grep -c processor           # RK3576J: 8 (4×A72 + 4×A53)

# 2) NPU 驱动是否在
ls /dev | grep -i rknpu                         # 期望 rknpu / rknpu0 之类
dmesg | grep -i -E 'rknpu|npu' | tail -20

# 3) NPU 负载与频率
cat /sys/kernel/debug/rknpu/load 2>/dev/null || echo "no debugfs load node"
cat /sys/class/devfreq/*npu*/cur_freq 2>/dev/null
cat /sys/class/devfreq/*npu*/available_frequencies 2>/dev/null

# 4) RKNN runtime
ls -l /usr/lib/librknnrt.so /usr/lib64/librknnrt.so 2>/dev/null
strings /usr/lib/librknnrt.so | grep -i -m3 'librknnrt version\|rknnrt'
ldconfig -p | grep rknn

# 5) 温度/功耗（连续跑时监控）
cat /sys/class/thermal/thermal_zone*/temp
```

**判定**：
- 没有 `/dev/rknpu*` → 驱动没起，先解决固件，别往下走；
- `librknnrt.so` 缺失或版本 < 转换端 toolkit → 从同版本 toolkit 包里拷一份（见 §4）。

---

## 4. 把运行库与头文件放到板子上

从 `rknn-toolkit2` 发布包的 `rknpu2/runtime/Linux/librknn_api/`：

```
include/rknn_api.h            -> /usr/include/
include/rknn_matmul_api.h     -> /usr/include/        (可选)
aarch64/librknnrt.so          -> /usr/lib/
```

```bash
# PC 侧
adb push librknnrt.so /tmp/ ; adb push rknn_api.h /tmp/
# 板子侧
sudo cp /tmp/librknnrt.so /usr/lib/ && sudo ldconfig
sudo cp /tmp/rknn_api.h   /usr/include/
```

> 若板厂镜像已自带 `/usr/lib/librknnrt.so`，**先用 `strings | grep version` 比对版本**，
> 版本一致就不要覆盖。

---

## 5. 传模型上板

```bash
# 方式一：adb
adb push out/v3_960_fp16.rknn /userdata/
adb push out/v3_960_int8.rknn /userdata/

# 方式二：scp
scp out/*.rknn <用户名>@<板子IP>:/userdata/

# 方式三：板子上起 http 服务/挂 U 盘（同上，注意 /userdata 空间）
df -h /userdata
```

传完校验：
```bash
sha256sum /userdata/*.rknn
# 与 PC 端 SHA256SUMS.txt 比对，必须一致
```

---

## 6. 编译 C++ 程序（板端）

```bash
# 板端需要：cmake、g++、librknnrt.so、rknn_api.h
sudo apt update && sudo apt install -y cmake g++        # 若板厂源可用
cd /userdata/cpp
./build.sh                     # = cmake -S . -B build && cmake --build build
# 若头/库不在默认路径：
./build.sh -DRKNN_INC=/opt/rknn/include -DRKNN_LIB=/opt/rknn/lib
```

编译产物：`build/rknn_v3_detect`

**注意**：本机（Windows）**没有编译器**，这段代码**未被编译验证过**。
首次编译若报 `rknn_set_core_mask` 未声明，说明你的 `rknn_api.h` 太老（<1.6），
代码里已用 `#ifdef` 兜底——会退化成"只设 AUTO"，并打印警告。

---

## 7. 单帧测试

准备一张 **GRAY8 原始帧**（OV9281 输出的就是这种：1920×1080 单通道，无头无压缩）：

```bash
# 如果是 .pgm，直接给
./build/rknn_v3_detect --model /userdata/v3_960_int8.rknn --input /userdata/frame.pgm

# 如果是裸 .raw，要指定宽高
./build/rknn_v3_detect --model /userdata/v3_960_int8.rknn \
                       --input /userdata/frame_1920x1080.raw --width 1920 --height 1080
```

正常输出（一行 JSON）：
```json
{"image":"/userdata/frame.raw","image_width":1920,"image_height":1080,
 "detections":[{"class_id":2,"class_name":"racket","confidence":0.78,
                "bbox_xyxy":[1201.5,332.0,1388.2,640.7],
                "bbox_xywh":[1201.5,332.0,186.7,308.7]}]}
```

**第一次只看三件事**：
1. 有没有输出（能否拉到 NPU）；
2. 框在不在合理位置（可用手机拍屏幕、或把框画回图上肉眼比对）；
3. 三类是否都能出（换个含球的帧试）。

---

## 8. 连续 500 帧 Benchmark

```bash
# 单核
./build/rknn_v3_detect --model /userdata/v3_960_int8.rknn \
  --input /userdata/frame.raw --width 1920 --height 1080 \
  --bench 500 --core-mask 0

# 另一核
... --core-mask 1

# 双核协同
... --core-mask 0_1

# 自动（runtime 自己选）
... --core-mask auto
```

输出示例（**这是格式，不是实测值**）：
```json
{"frames":500,"pre_ms":...,"npu_ms":...,"post_ms":...,
 "total_mean_ms":...,"total_p50_ms":...,"total_p95_ms":...,"fps":...}
```

**四个必测项**：
| 项 | 看哪个字段 |
| --- | --- |
| 预处理 | `pre_ms`（Gray3 + 双线性 letterbox） |
| NPU 纯推理 | `npu_ms` |
| 后处理（解码+NMS） | `post_ms` |
| 端到端 | `total_*` 与 `fps` |

同时另开一个 shell 采样：
```bash
while true; do cat /sys/kernel/debug/rknpu/load; sleep 1; done   # NPU 利用率
top -b -n1 | head -15                                            # CPU
free -m                                                          # 内存
```

---

## 9. 精度验收（板端/模拟器）

`.rknn` 的精度**必须在同一 509 张 val 上重测**，口径与 PC 完全一致：
阈值 ball 0.20 / hand 0.25 / racket 0.25，IoU 0.5，一对一贪心匹配。

- **方式 A（推荐，PC 端用 toolkit 模拟器）**：
  ```bash
  python3 convert_v3_to_rknn.py \
    --onnx pingpong_yolov8n_gray_3cls_v3_960_single_out.onnx \
    --calib calib/list.txt --out out/ --target rk3576 \
    --eval-dir /path/to/pingpong_unified_3cls_v5
  ```
  会打印每一类的 TP/FP/FN 与 P/R/F1（模拟器 ≠ 板端，但能快速判断量化损失）。

- **方式 B（板端实测）**：用 `rknn_v3_detect` 跑 509 张图，把 JSON 结果按上面的口径统计。

**INT8 验收线（不达标就不上）**：

| 类别 | 指标 | 门槛 | V3 FP32 基线 |
| --- | --- | ---: | ---: |
| Ball | Recall | **≥ 0.49** | 0.510 |
| Hand | F1 | **≥ 0.60** | 0.618 |
| Racket | Recall | **≥ 0.73** | 0.756 |

不达标 → 混合精度（把 `Conv` 首层/DFL 层保留 FP16）→ 再不行考虑 QAT。
**不要因为"能跑"就接受精度崩掉的 INT8。**

---

## 10. 常见错误排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `rknn_init failed: -1` / `invalid model` | 模型与 runtime 版本不匹配，或文件传坏了 | 比对版本；`sha256sum` 校验 |
| `rknn_init failed: -4` | 内存不足（多人共享 NPU/大模型） | 关掉其它 NPU 进程；`cat /sys/kernel/debug/rknpu/load` |
| `rknn_run failed` | 输入 shape/类型与模型不符 | 确认 960×960×3 NHWC uint8 |
| 检测框整体偏移 | pad 或 scale 算错（letterbox 约定不一致） | 用 `tools/verify_decode_pc.py` 对齐算法 |
| 三类分数全 0.5 左右 | 输入没归一化，或 mean/scale 配错 | RKNN config 用 `mean=[0,0,0] scale=[255,255,255]`，代码里不要再除 255 |
| INT8 后球全丢 | 量化把小目标特征压掉 | 混合精度；或提高校准集里小球样本比例 |
| 只检到手/拍、没有球 | **这是当前 C++ 主链路的预期行为**（`perception_engine` 故意丢 ball） | 本工具是独立测试程序，不受影响；接入主链路需 B 模块评审 |
| `core_mask` 不生效 | runtime/header 太老 | 升级 `librknnrt.so`；老版本只能用 AUTO |
| FPS 远低于预期 | 预处理在 CPU 上做、或单线程 | 用 RGA 做 resize；多线程喂帧；对比 `npu_ms` 与 `total` 找出瓶颈 |
| 双核没变快 | 模型太小，单核已打满 | 实测四种 core_mask 选最优，不要预设双核更快 |

---

## 11. 完整执行顺序（checklist）

- [ ] 串口/ADB 能进板子，记录 `uname -a`、`/proc/device-tree/compatible`
- [ ] `ls /dev | grep rknpu` 有设备
- [ ] `librknnrt.so` 版本 = 转换端 toolkit 版本
- [ ] Linux x86_64 转换机上跑 `convert_v3_to_rknn.py` 得到 FP16 与 INT8
- [ ] 传 `.rknn` 上板并 `sha256sum` 校验
- [ ] 板端 `./build.sh` 编译通过
- [ ] 单帧测试：三类能出、框位置正确
- [ ] 500 帧 benchmark × 4 种 core-mask
- [ ] INT8 精度：Ball R ≥ 0.49、Hand F1 ≥ 0.60、Racket R ≥ 0.73
- [ ] 记录 `npu_ms` / `total_ms` / FPS / NPU 负载 / 温度
- [ ] 与 30 FPS、50 FPS 目标对比，写进报告

**记住**：官方 YOLOv8n 640 INT8 单核 90.2 FPS 是**纯推理、640 输入、官方模型**的数字，
和我们的 960、三分类、含预处理的完整链路**不可直接比较**。
