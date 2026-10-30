# V3 类别过滤交付（Ball + Hand）· 队长说明

**模型还是 V3，权重一个字节都没改。** 这里只做一件事：**在推理出口把 Racket 丢掉**。

---

## 1. 这是什么

`v3_960_fp16_dfl_layout.rknn` 仍是三分类模型（ball / hand / racket）。
本包在**解码 + NMS 之后**加了一层类别过滤，让下游只收到 **ball 和 hand**。

| 项 | 值 |
|---|---|
| 模型 | `v3_960_fp16_dfl_layout.rknn`（13,038,908 B） |
| SHA256 | `1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b` |
| 输入 | 960×960，GRAY8 → 3 通道 → letterbox 填充 114 |
| 输出 | `dfl` [1,64,18900] + `scores_logits` [1,3,18900] |
| 过滤 | **保留 class 0(ball) / 1(hand)，丢弃 class 2(racket)** |
| 阈值 | ball 0.20 / hand 0.25（与 V3 一致，未改） |

**为什么不在模型里删掉 racket**：V9 双分类实验已经试过（真改结构、真训练），
Ball Recall 从 0.510 掉到 0.370（见 `artifacts/unified_3cls_v9/`）。
**Racket 的标注本身在帮 Ball**（球几乎总在球拍附近），删掉它精度反而崩。所以正确做法是：
**模型保留三类，出口裁掉不用的一类。**

## 2. 过滤前后精度完全一致（509 张验证集）

| 类别 | 指标 | 过滤前 | **过滤后** |
| --- | --- | ---: | ---: |
| Ball | TP / FP / FN | 51 / 11 / 49 | **51 / 11 / 49** |
| Ball | P / R / F1 / AP50 | 0.8226 / 0.5100 / 0.6296 / 0.4921 | **完全相同** |
| Hand | TP / FP / FN | 654 / 292 / 518 | **654 / 292 / 518** |
| Hand | P / R / F1 / AP50 | 0.6913 / 0.5580 / 0.6176 / 0.5042 | **完全相同** |
| Racket | 检出数 | 175 | **0** |

**509/509 帧**被保留的检测对象逐项完全相同（程序断言通过）。
过滤本身耗时 **0.0042 ms**（`decode+NMS 三类` 为 1.747 ms，同机 CPU）。

## 3. 怎么用

### 3.1 板端编译
```bash
cd cpp
./build.sh
# 头/库不在默认路径：./build.sh -DRKNN_INC=/opt/rknn/include -DRKNN_LIB=/opt/rknn/lib
# 老 SDK（无 rknn_set_core_mask）：./build.sh -DUSE_CORE_MASK=OFF
```

### 3.2 板端推理
```bash
./build/rknn_v3_detect_filtered --model ../v3_960_fp16_dfl_layout.rknn \
    --input frame.raw --width 1920 --height 1080 --classes 0,1
```

输出：
```json
{"image":"frame.raw","image_width":1920,"image_height":1080,"filtered_out":3,
 "detections":[{"class_id":1,"class_name":"hand","confidence":0.71,
                "bbox_xyxy":[..],"bbox_xywh":[左上x, 左上y, 宽, 高]}]}
```
- `filtered_out` = 本次被丢弃的 racket 框数（可观测，便于确认过滤生效）
- **只会出现 ball 与 hand**；`bbox_xywh` 用左上角坐标

### 3.3 PC 端复现验证
```bash
python3 tools/verify_filter.py --onnx pingpong_yolov8n_gray_3cls_v3_960_960.onnx \
    --dataset <repo>/artifacts/files/datasets/pingpong_unified_3cls_v5
```

## 4. ⚠ 与 BallTrack 的关系（重要，别踩坑）

现有正式链路 `software/pc_pipeline/modules/c_actual/src/perception_engine.cpp`
（第 210–224 行）已经**刻意丢弃 YOLO 的 ball**：

```
if (class_name == "hand")   -> result.hands
else if ("racket")          -> result.rackets
// "ball" is intentionally dropped: BallTrack 是唯一的球来源
```

**所以本包的程序是独立工具，不接入正式判罚链路。**
若要接入，正确改法只有一条：

| 类别 | 去向 |
| --- | --- |
| Hand | → `result.hands`（已有路径） |
| Racket | 已被本包过滤，不需要再处理 |
| **Ball** | **仍然保持丢弃**，或改由 B 模块评审后走独立通道 |

**绝不能**把 YOLO 的 ball 直接塞进 `result.balls` —— 会和 BallTrack 形成双球源，
两个球定义不同，模块 B 的跟踪会静默打架。这条必须由 B 模块负责人审核后由蒲公英批准。

## 5. 包里有什么

```
v3_960_fp16_dfl_layout.rknn        V3 FP16 RKNN（原文件，未改动）
pingpong_yolov8n_gray_3cls_v3_960_960.onnx   PC 端复现/校验用
filter_config.yaml                 类别过滤配置（keep [0,1], drop [2]）
cpp/rknn_v3_detect_filtered.cpp    推理 + DFL 解码 + 类别过滤
cpp/CMakeLists.txt                 编译脚本
cpp/build.sh                       一键编译
tools/verify_filter.py             509 帧等价性验证
filter_equivalence_509.json        验证原始输出
README_CAPTAIN.md                  本文件
EVALUATION_REPORT.md               精度与耗时报告
SHA256SUMS.txt                     全部文件校验和
```

## 6. 没有做的事（不编造）

| 项 | 状态 |
| --- | --- |
| AFH03 板端运行 | ❌ 未做（无实物） |
| NPU FPS / 单核双核 | ❌ 未测 |
| C++ 真实编译 | ❌ 本机无编译器 |
| 类别过滤提升 NPU 速度 | ❌ **不会提升**，模型仍算完三类 |

**类别过滤不会让 NPU 前向变快。** 它省掉的只是 racket 那部分后处理与下游传递，
而过滤本身只花 0.0042 ms。不要把它当性能优化。
