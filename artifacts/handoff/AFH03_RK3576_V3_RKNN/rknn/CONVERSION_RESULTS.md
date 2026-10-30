# RKNN 转换结果（WSL2 实测，2026-10-30）

**这里第一次出现了真实的 `.rknn` 文件。** 它们由 WSL2 + `rknn-toolkit2 2.5.0` 在本机生成，
**不是板端结果**，也没有任何 FPS 数据。

## 1. 结论速览

| 项 | 结果 |
| --- | --- |
| 转换环境 | **WSL2 Ubuntu 24.04 / Python 3.12.3 / rknn-toolkit2 2.5.0**（manylinux wheel） |
| FP16 转换 | ✅ **成功**，13,025,519 B，`v3_960_fp16_rk3576.rknn` |
| FP16 模拟器精度 | ✅ 基本保持（300 张 val：Hand P 0.681 / R 0.546 / F1 0.606 / AP50 0.496） |
| **INT8 转换** | ⚠️ **能出文件（9,847,626 B），但输出被量化破坏，不可用**（见 §4） |
| 板端加载/推理/FPS | ❌ **BLOCKED**（无 AFH03 实物） |

## 2. 两条重要修正（与上一轮结论相反，必须记住）

### 2.1 单输出 ONNX **不能**用于转换

上一轮我建议"用单输出版转换"。实测：**单输出版在 RKNN 2.5.0 的图优化器里直接崩**：

```
File "rknn/api/rules/conv.py", line 4860, in _p_seperate_conv_rs_split
IndexError: list index out of range
```

（`optimization_level` 0/1/3 都一样崩。）

**原始 6 输出 ONNX（`b779c88e…`）反而能成功转换**。原因是单输出版本经过 ultralytics 的
`simplify=True`，引入的 Split 模式正好触发该 fusion 规则的 bug。

→ **转换用原始 6 输出模型；单输出版仅用于 PC 侧评测。** 这一条已写进 README/指南。

### 2.2 INT8 的真正障碍不是校准集，而是**输出布局**

`output0 = concat(box(4), score(3))` 把 **0~960 的框坐标**和 **0~1 的分数**放进同一张量。
RKNN 对整张张量做单尺度量化 → 分辨率被坐标量程主导 → 分数全被压平。

实测证据（模拟器，同一张图）：

| 模型 | output0 数值范围 |
| --- | --- |
| FP16 | 正常（分数 0~1，可解出 box+score） |
| INT8 | **min −15.3 / max 956.1 / mean 162.5**（max≈960 说明被坐标量程支配） |

结果：INT8 模型在 300 张 val 上**检出为 0**。

**正确做法**（官方 `rknn_model_zoo/examples/yolov8` 就是这么干的）：
导出时**去掉最后的 Concat**，让模型输出分离的张量（每个尺度一份 score 图 + 一份 DFL 分布），
在 C++ 侧自己跑 DFL 解码。这样框坐标和分数各自量化，INT8 才可能保住精度。

## 3. FP16 精度（RKNN 模拟器，300 张 val，`rk3588` 代理配置）

| 类别 | P | R | F1 | AP50 |
| --- | ---: | ---: | ---: | ---: |
| Hand | 0.681 | 0.546 | 0.606 | 0.496 |

- 这 300 张是排序后的前 300 张，**全部是 `vbh_*`（影视剧手部图）**，所以 Ball/Racket 的 GT 为 0，
  无法在这一子集上评估。
- 对照 PC 端 FP32（全 509 张）：Hand P 0.691 / R 0.558 / F1 0.618 / AP50 0.504。
- → **FP16 的量化损失约 1–2 个点**，属于正常范围。

⚠ 两点必须注意：
1. 这是**模拟器**（`target_platform='rk3588'`），因为 toolkit 2.5.0 的模拟器**不接受 `rk3576`**
   （`The 'target' is simulator, but your config.target_platform is 'rk3576'`）。
   所以这组数字是**代理值**，不是 rk3576 实机数字。
2. 板端必须用**同版本** `librknnrt.so` 加载，否则 `rknn_init` 会因版本不匹配失败。

## 4. 文件清单与哈希

| 文件 | 大小 | SHA256 | 状态 |
| --- | ---: | --- | --- |
| `v3_960_fp16_rk3576.rknn` | 13,025,519 | `f6354f2e703f23914d34ce93431d4a940f188ea954de5010d8d79a425bf675a0` | ✅ 可试板端加载 |
| `v3_960_int8_rk3576_BROKEN_concat_quant.rknn` | 9,847,626 | `7579c08ae0ebd0b00de4746df30ac75e84ff0819efdd69ede86614a362a05b04` | ❌ **不要用**，仅作问题证据 |
| `fp16_sim_accuracy_300imgs.json` | 664 | `62113cf970569bc6ea81a2b498747ee4c26c0b2daa96a7dcdeaee1c2f812ec59` | FP16 模拟器精度原始记录 |

## 5. 复现命令（WSL / Linux x86_64）

```bash
# 0) 环境（实测可行）
python3 -m pip install --user --break-system-packages rknn-toolkit2 \
      onnx==1.18.0 protobuf==4.25.4 numpy==1.26.4 onnxruntime \
      'torch==2.4.0' --index-url https://download.pytorch.org/whl/cpu   # torch 单独装

# 1) FP16（用 6 输出 ONNX！）
python3 - <<'PY'
from rknn.api import RKNN
r = RKNN(verbose=False)
r.config(target_platform='rk3576', mean_values=[[0,0,0]], std_values=[[255,255,255]], optimization_level=3)
assert r.load_onnx(model='pingpong_yolov8n_gray_3cls_v3_960_960.onnx') == 0   # 6 输出
assert r.build(do_quantization=False) == 0
r.export_rknn('v3_960_fp16_rk3576.rknn')
PY

# 2) 模拟器精度（build 与推理必须同一进程，不能用 load_rknn）
python3 tools/build_and_eval_sim.py --onnx pingpong_yolov8n_gray_3cls_v3_960_960.onnx \
    --platform rk3588 --val val_imgs --labels val_labels --limit 300 --tag fp16_sim
```

## 6. 下一步（要真正拿到 INT8）

1. **改导出**：去掉 Detect 末尾的 Concat，输出 3 个尺度的 score 图 + 3 个 DFL 张量（共 6 个）。
   直接参考 `rknn_model_zoo/examples/yolov8` 的 `export_onnx`（它已经处理了这一步）。
2. **C++ 侧补 DFL 解码**：`softmax(DFL)·arange(16)` 得到距离，再加到 anchor 上。
   当前 `rknn_v3_detect.cpp` 解的是 concat 后的 `[7,18900]`，**需要新增一条 DFL 分支**。
3. 重新量化并按 §7 的验收线检查。

## 7. 验收线（未变）

| 类别 | 指标 | 门槛 |
| --- | --- | ---: |
| Ball | Recall | ≥ 0.49 |
| Hand | F1 | ≥ 0.60 |
| Racket | Recall | ≥ 0.73 |
