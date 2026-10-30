# V3 检测头计算图审计（拆分前）

日期：2026-10-30　源：`pingpong_yolov8n_gray_3cls_v3_960_960.onnx`
SHA256：`b779c88e08f8bd15275e301c00bcbfb9c737fc22fa4ef1c358008f0b932254ba`（**未修改**）

## 1. 原始输出（实查，不靠命名猜）

| # | 名称 | shape | 含义（由图结构确证） |
| --- | --- | --- | --- |
| 0 | `output0` | `[1, 7, 18900]` | **拼接后的最终检测张量**（4 框 + 3 类分数） |
| 1 | `onnx::Reshape_725` | `[1, 64, 18900]` | **DFL logits**（4 边 × 16 桶） |
| 2 | `onnx::Sigmoid_769` | `[1, 3, 18900]` | **类别 logits（sigmoid 之前）** |
| 3 | `onnx::Conv_607` | `[1, 64, 120, 120]` | P3/8 特征图 |
| 4 | `onnx::Conv_643` | `[1, 128, 60, 60]` | P4/16 特征图 |
| 5 | `onnx::Conv_679` | `[1, 256, 30, 30]` | P5/32 特征图 |

## 2. `output0` 是怎么拼出来的（节点级证据）

```
output0 = Concat( /model.22/Mul_2_output_0 , /model.22/Sigmoid_output_0 )
                        │                          │
                        │                          └─ Sigmoid( onnx::Sigmoid_769 )
                        │                                 = 类别分数 in 0..1
                        └─ Mul( /model.22/Concat_6_output_0 , Constant_25 )
                                 = dist2bbox 结果 × stride
                                 = **最终 xyxy，单位是 960 输入空间像素（0..960）**
```

两条事实：

1. **框分支已经是最终 xyxy**，不是 DFL 距离、也不是 4 通道 logits；
2. **分数分支是 sigmoid 之后的概率（0..1）**。

## 3. 量纲差异（INT8 崩掉的根因）

| 分支 | 取值范围 | 需要的分辨率 |
| --- | --- | --- |
| 框坐标 | **0 – 960** | 约 1 px |
| 类别分数 | **0 – 1** | 约 0.01 |

把两者放进同一个 `output0` 张量后，RKNN 只能给**一个 scale**。这个 scale 由 0..960 的坐标
量程决定，于是 0..1 的分数被压到几乎全部落在同一个量化格子里。

**实测证据**（上一轮，模拟器同一帧）：

| 模型 | `output0` 反量化后的数值范围 |
| --- | --- |
| FP16 | 正常（分数 0..1） |
| INT8 | min −15.3 / **max 956.1** / mean 162.5 |

→ INT8 在 300 张 val 上**检出 0 个框**。

## 4. 拆分方案与实测结果

| 方案 | 输出 | 转换 | 结果 |
| --- | --- | --- | --- |
| 只保留拆分输出（删除 `output0`） | `boxes[1,4,N]` + `scores[1,3,N]` | ❌ **RKNN 2.5.0 崩溃**（`_p_seperate_conv_rs_split` IndexError） | 不可用 |
| **保留全部原输出 + 附加 `boxes`/`scores`**（keep-all） | 8 个输出 | ✅ 成功 | INT8 有检出，但分数仍被压缩（hand F1 **0.458**） |
| **保留全部原输出 + 用 DFL/类别 logits 解码**（本轮的最终方案） | 复用已有输出 1、2 | ✅ 成功 | **hand F1 0.5906**，接近 FP16 的 0.6075 |

### 为什么 DFL 布局胜过 `scores`

`scores` 是 `output0` 的 Concat **输入**，RKNN 会把它和 concat 一起量化 → 继承粗 scale。
而 `onnx::Reshape_725`（DFL logits）与 `onnx::Sigmoid_769`（类别 logits）**只服务于最终输出**，
不与框坐标共享量化尺度 → 各自拿到合适 scale。

实测 logits 范围：**FP16 −38.9..2.5**，**INT8 −40.7..2.3**（几乎一致）→ 说明 logits 的量化是健康的。

## 5. 拆分前后一致性（PC 端，ONNX 级）

| 检查 | 结果 |
| --- | --- |
| `cat(boxes, scores)` vs 原 `output0` | **逐元素最大差 = 0.0**（60 张，0 帧超 1e-3） |
| 解码后逐类指标（orig / split / dfl 三种解码） | **完全相同**：hand TP 107 / FP 42 / FN 83，P 0.7181 / R 0.5632 / F1 0.6313 / AP50 0.5224 |

→ 拆分**没有改变任何数值**：它只是把同一个张量在出口处分开放置，权重与算术完全未动。

## 6. 结论

1. `output0` 的 4+3 拼接是 INT8 失败的唯一根因，已由图结构与数值双重确认；
2. **正确的量化出口是 DFL logits + 类别 logits**（或单独的 boxes+scores），文档中的
   "max 956 / mean 162" 现象由此消失；
3. C++ 侧因此需要实现 DFL 解码（softmax/16 → 期望 → dist2bbox），本轮已提供并通过 PC 端
   数值核验（见 `cpp/rknn_v3_detect.cpp` 的 `--layout dfl`）。
