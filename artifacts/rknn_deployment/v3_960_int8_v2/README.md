# V3 RKNN INT8 修复 · 交付说明

**状态：FP16 可交付；INT8 已修复到可用但 Ball Recall 0.470 < 0.49，暂不作为正式候选。**

没有 AFH03 实物，所以**没有任何板端数字**：NPU FPS、单/双核延迟、P95、完整流水线 FPS 全部 BLOCKED。
所有精度数字来自 **rknn-toolkit2 2.5.0 模拟器**（`target_platform='rk3588'` 代理配置，因为该版本
模拟器不接受 `rk3576`）。

## 1. 一句话结论

INT8 从"检出 0 个框"修复到"hand F1 0.6043 / racket R 0.7557 / ball R 0.4700"，
**根因是输出布局而不是校准集**：把框坐标与类别分数拼在同一个张量里，RKNN 只能给一个 scale，
分数被坐标量程压平。改用 DFL logits + 类别 logits 作为量化出口后，问题消失。

## 2. 目录

| 路径 | 说明 |
| --- | --- |
| `rknn/v3_960_fp16_dfl_layout.rknn` | **FP16，可交付**（与 FP32 差 ≤1.3 点） |
| `rknn/v3_960_int8_dfl_layout.rknn` | INT8，Ball Recall 差 2 点，**暂不交付** |
| `pingpong_v3_960_split_keepall.onnx` | 转换用（原 6 输出 + 附加 `boxes`/`scores`） |
| `pingpong_v3_960_split.onnx` / `_dfl.onnx` | 拆分实验件（仅 PC 评测） |
| `cpp/rknn_v3_detect_dfl.cpp` | C++ 推理 + DFL 解码（`--layout dfl|split`、`--core-mask`、`--bench`） |
| `configs/fp16_960.yaml`、`configs/int8_960.yaml` | 转换配置 |
| `calib_list.txt` | 300 张校准清单（只用 train，0 张来自 val） |
| `accuracy/*.json` | 300/509 张的逐类结果 |
| `V3_DETECTION_HEAD_GRAPH_AUDIT.md` | 计算图审计（节点级证据） |
| `INT8_FIX_REPORT.md` | 三条转换路线对比与精度表 |
| `verify_60.json` | 拆分前后一致性（max 差 0.0） |
| `make_split_*.py`、`verify_split_onnx.py`、`eval_dfl_sim.py` | 可复现脚本 |

## 3. 关键数字（509 张固定 val）

| 类别 | FP32 ONNX | FP16 RKNN | INT8 RKNN | 门槛 |
| --- | --- | --- | --- | --- |
| Ball R | 0.5100 | **0.5100** | 0.4700 | ≥0.49 ❌ |
| Hand F1 | 0.6176 | **0.6182** | 0.6043 | ≥0.60 ✅ |
| Racket R | 0.7557 | **0.7557** | 0.7557 | ≥0.73 ✅ |

## 4. 板端命令（拿到 AFH03 后）

```bash
cd cpp && ./build.sh
# FP16（先用这个验证链路）
./build/rknn_v3_detect --model ../rknn/v3_960_fp16_dfl_layout.rknn \
   --input /userdata/frame.raw --width 1920 --height 1080 --layout dfl
# 500 帧基准 ×4 种 core-mask
./build/rknn_v3_detect --model ... --bench 500 --core-mask auto
./build/rknn_v3_detect --model ... --bench 500 --core-mask 0
./build/rknn_v3_detect --model ... --bench 500 --core-mask 1
./build/rknn_v3_detect --model ... --bench 500 --core-mask 0_1
```

输出 JSON 与 C 模块契约一致：`class_id / class_name / confidence / bbox_xyxy / bbox_xywh`
（xywh 为左上角约定）。

## 5. 未完成

- 板端加载/精度/性能（BLOCKED：无实物）
- C++ 编译（本机无编译器；算法已在 Python 侧逐数值核验）
- 逐张量 scale/zero-point 导出（需板端 `rknn_query`，C++ 已打印 `qnt_type`）
- Ball Recall 差 2 点的最终修复（建议：加大球类校准量 or DFL 分支保留 FP16 混合精度）
