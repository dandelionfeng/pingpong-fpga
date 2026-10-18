# HAND V3 报告

日期：2026-10-18　分支：`codex/c-pc-detector`

## 0. 一句话结论

**V3 raw 在 Precision 与 Recall 上同时提升（P 0.3626→0.4023，R 0.6111→0.6481，
F1 0.4552→0.4965，AP50 0.3789→0.4670），建议 UPGRADE TO V3。**
**Temporal filter 无效**（在合法连续数据上仅抑制 3.03%，在稀疏 GT 上只会杀 Recall），
不作为降 FP 手段。

## 1. 防泄漏范围

`BNDSTT_MANUAL_GT_V1` 只用于最终测试。整段来源 session 全部排除出所有训练/挖掘池：

```
20240428_145028_Output_Group1
20240503_163810_Output_Group1
20240503_164411_Output_Group1
20240524_183430_Output_Group1
20240524_183648_Output_Group1
```

可用非泄漏视频：**28 个 session / 707 个 mp4**，本次使用其中 150 个视频 × 12 帧 =
**1,800 帧**。

checkpoint 选择只看 **BodyHands val**（1,258 图 / 3,332 实例），从未用 GT 挑 epoch。

## 2. Pseudo-positive

| 项 | 值 |
| --- | --- |
| 扫描帧 | 1,800 |
| **pseudo-positive 图片** | **1,549** |
| **pseudo-positive bbox** | **1,886** |

筛选规则（**接触 GT 之前冻结**）：

| 规则 | 阈值 |
| --- | --- |
| hand confidence | **≥ 0.45** |
| bbox 尺寸 | W,H ∈ [18, 220] px @1920×1080 |
| wrist 门限 | 高置信 wrist（≥0.30）落在 bbox 外扩 0.6×最长边内，**或**距中心 ≤1.2×对角线 |
| 时序一致性 | 前 2 帧中**至少 1 帧**匹配（IoU ≥0.30 或 中心距 ≤0.6×对角线） |

**hand bbox 只来自 YOLO hand detector（V2.2 960）。wrist 仅作验证门限，绝不造框。**

## 3. Hard negative

| 项 | 值 |
| --- | --- |
| hard-negative 图片 | **232** |
| hard-negative 候选框 | **376** |

| 原因 | 数量 |
| --- | --- |
| 孤立单帧（前后无匹配） | 213 |
| 尺寸异常 | 128 |
| 附近无 wrist | 35 |

加入方式：整帧 + **空 label 文件**，让模型学会在该帧不报手。
只取"达到部署阈值 0.25 但不满足可信条件"的框，不把不确定案例强行当负样本。

## 4. HAND_DOMAIN_V3 构成

| 来源 | 数量 | 占比 |
| --- | --- | --- |
| BodyHands 真实标注（主体） | **5,000** | 73.7% |
| pseudo-positive | 1,549 | 22.8% |
| hard-negative | 232 | 3.4% |
| **train 合计** | **6,781** | 100% |
| val（仅 BodyHands val） | 1,258 | —— |

**pseudo 域占比 26.3%**，落在要求的 10–30% 区间内；BodyHands 仍是主体。
输入统一 RGB → GRAY → 复制 3 通道；单类 `hand`。

> 过程中发现并修复一次数据污染：上一版 `hand_domain_v3` 目录残留 `v3_*` copy-paste
> 文件，导致 train 达 13,197（含 6,416 旧合成图）。已改为**每次构建先清空目录**后重建。

## 5. Fine-tune

| 项 | 值 |
| --- | --- |
| 起点 | `bodyhands_hand_960/weights/best.pt`（**继续训练，非从头**） |
| imgsz | 960 |
| epochs 设定 / 实际 | 15 / **7**（early stopping patience=5 触发） |
| lr0 | **0.001**（低 LR），lrf 0.01 |
| batch | 8 |
| 耗时 | 1,744.5 s |
| BodyHands val best | mAP50 **0.803** / mAP50-95 **0.417**（V2.2 起点 0.823 / 0.433） |

## 6. 三个结果对比（BNDSTT_MANUAL_GT_V1，41 图 / 54 hand GT，conf 0.25）

| 方案 | P | R | F1 | AP50 | TP/FP/FN |
| --- | --- | --- | --- | --- | --- |
| **A. V2.2 raw** | 0.3626 | 0.6111 | 0.4552 | 0.3789 | 33/58/21 |
| **B. V3 raw** | **0.4023** | **0.6481** | **0.4965** | **0.4670** | **35/52/19** |
| **C. V3 + temporal** | 0.4035 | 0.4259 | 0.4144 | —— | 23/34/31 |

### 关于 C 的合法性（重要）

**TEMPORAL_METRIC_LIMITED。**

`BNDSTT_MANUAL_GT_V1` 的 5 个 session 共 36 个相邻 GT 帧对，其中**只有 4 对是真正连续帧**
（间隔=1），其余间隔 4–6 帧。temporal filter 需要连续帧才能确认轨迹，因此在这种稀疏
采样上，真实手经常显得"孤立"而被抑制——上表 C 行 Recall 从 0.6481 崩到 0.4259 就是这个
原因，**不是 filter 真实性能**。

**该行数字不能作为 temporal filter 的有效指标，不构成任何提升声明。**

### 有效的替代证据（无 GT，描述性）

在**真正连续**的 40 帧视频上（`sample_clip.mp4`）：

| 项 | 值 |
| --- | --- |
| raw hand 框 | 66 |
| 经 temporal 确认 | 64 |
| 抑制率 | **3.03%** |

即：在合法连续输入上，filter 只去掉 3%，**对降 FP 几乎没有作用**。

## 7. 目标达成情况

| 目标 | 要求 | 实际 | 判定 |
| --- | --- | --- | --- |
| Precision | ≥ 0.50（最好） | **0.4023** | 改善但未达标 |
| Recall | ≥ 0.55 | **0.6481** | 达标 |
| F1 | > 0.4552 | **0.4965** | 达标 |
| Recall 不崩 | —— | 0.6111→0.6481（**升**） | 达标 |

## 8. 部署决定

**UPGRADE TO V3。**

- F1 0.4965 > 0.4552 ✓
- Precision 0.3626 → 0.4023（相对 +11%，TP +2、FP −6）✓
- Recall 0.6111 → 0.6481（未崩，反而升）✓

导出：`hand_yolov8n_gray_final_v3_960.onnx`
- 12,159,554 bytes，SHA256 `959ed6c4014fe62ac09f4ef62670f992edf115ce517780d5cca9e3abf157eed4`
- 输入 `[1,3,960,960]`，输出 `[1,5,18900]`，单类 `hand`

**Temporal filter：不采用为降 FP 手段**，仅作为 B 侧可选 helper 交付。

## 9. C++ / parity / 回归

| 项 | 结果 |
| --- | --- |
| C++ 加载（hand 960 + racket 640 + BallTrack） | **PASS**（`SELF-TEST OK`，版本 `c_actual-v2.3-interface`） |
| 真实检出 hand | **PASS**（40 帧视频 66 个 hand 框，37/40 帧有检出） |
| ball / racket 未受影响 | **PASS**（ball DETECTED 29/40，racket 28 框，与 V2.2 完全一致） |
| 检测器错误 | **0** |
| Python/C++ hand parity | **PASS**（66 vs 66 框，0 数量差异，66/66 匹配，max 0.000893 px） |
| image / video demo | **PASS**（exit 0，overlay 正常） |
| `tools/check_repo.py` | 262 tracked files, 0 problems |
| `pytest` | 94 passed |
| `unittest` | 30 OK |
| C++ tests（无模型 / 960+640） | 20/20 / **24/24** PASS |

## 10. 交付物

| 项 | 位置 |
| --- | --- |
| V3 ONNX | `artifacts/files/models/hand_v3_960/hand_yolov8n_gray_final_v3_960.onnx` |
| Temporal filter helper（B 侧可选） | `software/pc_pipeline/modules/c_actual/python/temporal_hand_filter.py` |
| 数据集 manifest | `reports/HAND_V3_DATASET_MANIFEST.json` |
| 配置 | `config/inference.yaml`（`version: C_ACTUAL_INTERFACE_V2_3`，hand → v3 onnx） |

`onnx / pt / mp4 / zip / dataset` **均未提交 Git**；C 原始 `DetectionResult` 接口未改动。

## 11. 未做 / 非阻塞

- **未重建 captain zip**（V2.3 包需要时再打；当前线上包仍是 V2.2）。
- Temporal filter 未做参数搜索（会违反"不用测试集调参"）。
- 未引入 Kalman，未做 hand role 判断。
