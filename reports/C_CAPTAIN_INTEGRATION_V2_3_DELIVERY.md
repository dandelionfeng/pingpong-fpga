# C 模块 V2.3 最终交付记录

日期：2026-10-18　分支：`codex/c-pc-detector`　HEAD：`90cc40b`（+ 本次文档/测试修正）

## 1. 交付包

| 项 | 值 |
| --- | --- |
| 文件名 | `C_PERCEPTION_CAPTAIN_INTEGRATION_V2_3.zip` |
| 绝对路径 | `D:\电脑管家迁移文件\xwechat_files\wxid_ttrefx9qt9o722_32d9\msg\file\2026-10\方案及分工\方案及分工\pingpong-fpga\artifacts\handoff\C_PERCEPTION_CAPTAIN_INTEGRATION_V2_3.zip` |
| 大小 | 105,692,524 bytes（100.80 MB） |
| SHA256 | `da60219a8d55dba284360c4063868cb8f32154b599caf7c4107572418bc40bc4` |
| ZIP 条目 | 26 |
| V2.1 / V2.2 | **保留，哈希未变** |

## 2. 包内文件清单

```
C_PERCEPTION_CAPTAIN_INTEGRATION_V2_3/
├─ bin/
│  ├─ c_perception_cli.exe                  172,032
│  ├─ c_actual_tests.exe                    151,040
│  ├─ onnxruntime.dll                     11,569,696
│  ├─ opencv_world4100.dll                64,653,312
│  └─ opencv_videoio_ffmpeg4100_64.dll    26,391,552
├─ models/
│  ├─ balltrack_tracknetv3.onnx           45,330,200
│  ├─ hand_yolov8n_gray_final_v3_960.onnx 12,159,554
│  └─ racket_yolov8n_gray.onnx            12,117,766
├─ sdk/
│  ├─ include/c_perception_engine.hpp
│  ├─ lib/c_actual.lib                     1,437,844
│  ├─ lib/c_actual_pipeline_bridge.lib     1,660,946
│  ├─ detector_backend_c_actual.cpp
│  └─ INTERFACE_CONTRACT.md
├─ python/temporal_hand_filter.py          （B 侧可选，不改 C 输出）
├─ config/inference.yaml
├─ examples/{sample_frame.png, sample_clip.mp4, expected_result_sample.jsonl}
├─ INTERFACE_CONTRACT.md
├─ README_CAPTAIN.md
├─ THIRD_PARTY_NOTICES.md
├─ C_PERCEPTION_CAPTAIN_INTEGRATION_V2_3_REPORT.md
├─ MODEL_SHA256.txt
├─ BUILD_INFO.txt
├─ VERSION.txt
└─ run_demo.ps1
```

## 3. 模型版本核对

| 模型 | SHA256 | 与上一版关系 |
| --- | --- | --- |
| ball `balltrack_tracknetv3.onnx` | `2e9ddd9c…739a93` | **与 V2.1/V2.2 完全相同** |
| hand `hand_yolov8n_gray_final_v3_960.onnx` | `959ed6c4014fe62ac09f4ef62670f992edf115ce517780d5cca9e3abf157eed4` | **本版新增（V3）** |
| racket `racket_yolov8n_gray.onnx` | `e606e8de…703f7` | **与 V2.1/V2.2 完全相同** |

ZIP 内**不含** `hand_yolov8n_gray_interface_v1.onnx` 或 `hand_yolov8n_gray_final_v2_960.onnx`
（已校验 `NONE`）；文本文件中**无绝对路径**（扫描命中 0）。

## 4. 实际运行结果（解压到 `C:\cap_v23final` 后）

```
run_demo.ps1  ->  exit 0
image demo    ->  Done. frames=1
video demo    ->  Done. frames=40  ball DETECTED=29 WARMUP=4 DROPOUT=7
                  hand boxes=66  racket boxes=28
                  mean inference 1855.43 ms/frame
输出: out/result_image.jsonl, out/result_video.jsonl,
      out/overlay_image.png (1,353,676 B), out/overlay_video.mp4 (1,881,978 B)
```

- hand 模型确认为 `hand_yolov8n_gray_final_v3_960.onnx`
- **无检测器错误警告**（40 帧 JSONL 中 `MISMATCH/INVALID/FAILED` 命中 0）
- ball 与 racket 输出与 V2.2 一致（29/40 与 28 框），证明未被替换

## 5. hand 真实域成绩（不得夸大）

`BNDSTT_MANUAL_GT_V1`，**41 图 / 54 个 hand box / 5 个 session**，conf = 0.25，单次测量：

| 指标 | 值 |
| --- | --- |
| Precision | **0.4023** |
| Recall | **0.6481** |
| F1 | **0.4965** |
| AP50 | **0.4670** |
| TP / FP / FN | 35 / 52 / 19 |

V2.2 为 P 0.3626 / R 0.6111 / F1 0.4552 / AP50 0.3789。

**样本极小（41 图 / 54 框 / 5 session），只能支持"方向可信"，不能作为对其他球场、
光照、机位、球员服装的泛化结论。** 未用该集合调阈值（hand_conf 固定 0.25），
未用该集合挑 checkpoint（按 BodyHands 验证集选）。

## 6. 验证矩阵（全部实际执行）

| 项 | 结果 |
| --- | --- |
| 一键 demo（全新英文目录解压） | **exit 0** |
| image demo / video demo | **PASS** |
| hand 960 与 racket 640 同时工作 | **PASS**（`hand=960` / `racket=640` 断言通过） |
| BallTrack 15 通道 gray3 | **PASS**（`tensor has exactly 15*H*W`、`[bg\|20\|30\|40\|50] × RGB`） |
| 无静默吞错 | **PASS**（40 帧 0 错误警告；给非法模型时 exit 3 + 明确 `Protobuf parsing failed`） |
| Python/C++ hand parity（用包内 exe） | **PASS**（66 vs 66 框，0 数量差异，66/66 匹配，max 0.000893 px） |
| `tools/check_repo.py` | 265 tracked files, **0 problems** |
| `pytest tests -q` | **94 passed** |
| `unittest discover -s tests` | **30 OK** |
| C++ tests（无模型） | **20/20** |
| C++ tests（960+640 混合） | **24/24** |
| C++ tests（含 BallTrack 15 通道） | **27/27** |

## 7. 本轮修复的真实缺陷

1. **`run_demo.ps1` 仍指向 V2.2 的 hand 文件名** → 解压后 demo 直接 `MISSING_MODEL`
   退出码 2。这是**实际运行才暴露**的问题，已改为 V3 文件名并同步标题。
2. **README 层叠历史导致事实错误**（V2.2 行的模型名被误写成 V3）→ 整体重写为 V2.3
   一致版本，过期段落删除。
3. **C++ 测试夹具写死短文件名**（`ball.onnx`）→ 对规范命名的交付包无法运行，
   改为按候选名解析（优先规范名，兼容旧短名）。
4. `INTERFACE_CONTRACT.md` 版本号仍为 V2_2 → 更新为 V2_3。

## 8. 未完成 / 限制（如实）

- **CPU 非实时**：1920×1080 约 1.8–1.9 s/帧，hand 960 是主要成本。
- **RKNN 未转换**、**无 NPU 实测**、**BOARD VERIFIED = NO**。
- **未接真实 OV9281 相机**：灰度链路在公开数据与解码视频帧上验证。
- BallTrack 背景为**首帧冻结**（官方为整段中位数，两者不等价），相机移动需重评估。
- Temporal filter 在连续片段上仅抑制约 3%，**不是降误检手段**；在稀疏评测集上
  指标为 `TEMPORAL_METRIC_LIMITED`。
- BodyHands 数据权利由作者声明为专有；`THIRD_PARTY_NOTICES.md` 已列出，含 AGPL-3.0。

## 9. Git

- 分支 `codex/c-pc-detector`，**未 push main，未 merge PR，未 force push**
- 未提交模型二进制 / 数据集 / 视频 / ZIP
- 本轮源码变更为：`README_CAPTAIN.md`、`INTERFACE_CONTRACT.md`、`run_demo.ps1`、
  `tests/test_c_actual.cpp`、本报告
