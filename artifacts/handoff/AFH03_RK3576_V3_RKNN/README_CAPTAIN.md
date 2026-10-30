# AFH03 / RK3576J 部署包说明（PC 端准备完成，板端 BLOCKED）

**状态：准备件，未经板端验证。没有 `.rknn` 文件，因为没有 RKNN 工具链和板子。**
不要把本包的任何内容当作"NPU 部署成功"或"达到 X FPS"。

## 1. 包里有什么

| 文件 | 说明 |
| --- | --- |
| `pingpong_yolov8n_gray_3cls_v3_960_single_out.onnx` | **转换用模型**：V3 权重的**单输出**导出版（`[1,3,960,960]` → `[1,7,18900]`），精度与原 V3 **完全一致** |
| `pingpong_yolov8n_gray_3cls_v3_640.onnx` | 640 对照实验用（**已实测不可用**，见 §4） |
| `convert_v3_to_rknn.py` | RKNN Toolkit2 转换脚本（FP16 + INT8 + 精度自检） |
| `make_calib_list.py` | 生成 INT8 校准清单（只用训练集） |
| `calib/list.txt` | 300 张校准图（五类场景各 60，**0 张来自验证集**）。⚠ 文件里是 **Windows 绝对路径**，在转换机上请用 `make_calib_list.py` 重新生成（或自行替换路径前缀） |
| `cpp/rknn_v3_detect.cpp` | RKNN C API 推理程序（含双核调度、分阶段计时） |
| `cpp/CMakeLists.txt`、`cpp/build.sh` | 板端编译 |
| `tools/verify_decode_pc.py` | C++ 解码算法核验（PC 端） |
| `ACCURACY_960.json`、`ACCURACY_640.json` | PC 端实测精度 |

## 2. 输入输出契约（不要改）

- 输入：**GRAY8**，复制成 3 个通道 → letterbox 到 960（填充 **114**）→ RKNN config 里用
  `mean=[0,0,0] scale=[255,255,255]` 完成 `/255`（**代码里不要再除一次**）
- 输出：`[1,7,18900]`，前 4 通道 `cx,cy,w,h`（960 空间像素），后 3 通道是 ball/hand/racket 分数
- 类别固定 **0=ball, 1=hand, 2=racket**（**不得重排**）
- 解码：按类 argmax → 置信度阈值（ball 0.20 / hand 0.25 / racket 0.25）→ 类内 NMS IoU 0.5
- 坐标：`x1=(cx-w/2-pad_x)/scale`，**原图像素**；`bbox_xywh` 用**左上角**约定（与 C++ `Box` 一致）

## 3. 怎么跑

```bash
# A. 转换（Linux x86_64 + rknn-toolkit2，Python 3.8-3.10）
python3 convert_v3_to_rknn.py \
  --onnx pingpong_yolov8n_gray_3cls_v3_960_single_out.onnx \
  --calib calib/list.txt --out rknn/ --target rk3576 \
  --eval-dir /path/to/pingpong_unified_3cls_v5

# B. 板端编译（AFH03 上）
cd cpp && ./build.sh      # 需要 /usr/include/rknn_api.h 和 /usr/lib/librknnrt.so

# C. 板端推理（GRAY8 原始帧）
./build/rknn_v3_detect --model rknn/*_int8.rknn --input frame.raw --width 1920 --height 1080
./build/rknn_v3_detect --model rknn/*_int8.rknn --input frame.raw --bench 500 --core-mask 0
./build/rknn_v3_detect --model rknn/*_int8.rknn --input frame.raw --bench 500 --core-mask 0_1
```

输出 JSON（与 C 模块 `DetectionResult` 对齐）：

```json
{"image":"frame.raw","image_width":1920,"image_height":1080,
 "detections":[{"class_id":1,"class_name":"hand","confidence":0.83,
                "bbox_xyxy":[412.5,236.0,598.2,470.7],
                "bbox_xywh":[412.5,236.0,185.7,234.7]}]}
```

## 4. 关键实测结论（先看这个，避免踩坑）

### 4.1 原 V3 ONNX 有 6 个输出，必须用单输出版转换

原文件除 `output0` 外还有 4 个 DFL/中间张量。用单输出重导后节点从 397 降到 234，
且**精度完全相同**（ball P/R/F1/AP50 = 0.823/0.510/0.630/0.492）。

### 4.2 640 分辨率**不可用**

| 分辨率 | Ball R | Ball AP50 | Hand R | Racket R |
| --- | ---: | ---: | ---: | ---: |
| **960** | **0.510** | **0.492** | 0.558 | 0.756 |
| 640 | **0.050** | 0.054 | 0.473 | 0.438 |

球在 640 输入下只剩 ~8 px，召回几乎归零。**不要为了 FPS 降到 640**（除非为 640 重新训练）。

### 4.3 INT8 精度必须在板端（或 toolkit 模拟器）验证

校准清单已按五类场景配平（ball_only / ball_racket / hand_only / racket_other / empty 各 60），
但**量化后的精度下降没有被测量过**——本机无 RKNN。验收门槛：
- Ball Recall ≥ 0.49
- Hand F1 ≥ 0.60
- Racket Recall ≥ 0.73

不达标就上混合精度（敏感层保留 FP16）或 QAT，**不要直接接受**。

### 4.4 C++ 算法已核验（不是板端结果）

`tools/verify_decode_pc.py`：40 帧上 C++ 的 letterbox/decode/NMS/坐标恢复与 Python 参考
**完全一致（IoU 1.000）**。C++ 代码本身**未编译**（本机无编译器，且需板端 `librknnrt.so`）。

### 4.5 与现有 C++ 管线的冲突点

`perception_engine.cpp` 目前的统一路径**故意丢弃 ball 类**（ball 唯一来源是 BallTrack）。
本包的 C++ 工具**独立输出三类**，不接入正式判罚链路；要接入必须由 B 模块评审，避免双球源。

## 5. 已知风险

1. **DFL 的 Slice/Shape/Gather/Softmax** 在 RKNN 上可能有精度或支持性问题 → 参考
   `rknn_model_zoo/examples/yolov8` 的导出方式。
2. **670 KB 的校准集不一定够**：若 INT8 精度掉太多，把 `--per-bucket` 提到 150–200。
3. **双 NPU 核不一定更快**：小模型单核常已打满，必须实测 `--core-mask` 四种配置再决定。
4. 官方 90.2 FPS 是 **640 INT8 单核纯推理**，与 960、与完整流水线、与我们的模型都不可比。

## 6. 未验证清单（全部 BLOCKED）

FP16/INT8 RKNN 转换 · RKNN 加载 · 板端精度 · 单核/双核 FPS · NPU 纯推理时间 ·
完整流水线 FPS · C++ 编译 · OV9281 接入 · RGA/FPGA 预处理 · RKNN 与 BallTrack 联调。
