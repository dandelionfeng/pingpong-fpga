# C 端感知 v2 — 当前状态

更新时间：2026-10-13（FINALIZATION 收口）

## 已完成

| 阶段 | 状态 |
| --- | --- |
| ZIP 获取与校验（SHA256 双端一致，testzip 无坏块） | DONE |
| 数据审计（1480 / 1036 / 291 / 153） | PASS（与公开 v2 页面完全一致） |
| ball+racket 二分类转换（0 ball / 1 racket） | DONE |
| QA contact sheet（train50 / val30 / test30） | DONE |
| GPU smoke（yolov8n + yolov8n-pose） | PASS |
| 短期训练 smoke（3 epochs, fraction 0.05） | PASS（产物单独标记 smoke3） |
| 正式训练（yolov8n, imgsz 640, 120 epochs, batch 16） | DONE（3101.6 s，best epoch 102） |
| test split 正式评估 | DONE（overall mAP50 0.7361） |
| ball 专项失败分析 + contact sheet | DONE |
| BNDSTT_30_V1 域内验证（detector + pose + fusion） | DONE |
| 延迟基准（warmup 20 + 100 迭代） | DONE |
| Operating point 曲线 + 三 profile | DONE |
| Temporal diagnostic（8 clips / 324 连续帧） | DONE |
| **Ball detector 最终 bake-off** | **DONE → FINAL BALL = BALLTRACK** |
| **PerceptionResultV2 冻结 + legacy adapter** | **DONE** |
| **ONNX 导出 + parity 校验（3 模型）** | **DONE → 全部 PASS** |
| **RKNN 部署准备** | **RKNN_PREPARED_NOT_EXECUTED** |
| 单元测试 | pytest 93 passed（本分支新增部分）／含既有测试合计 135 |
| RKNN / 板端实测 | **未做（无 Toolkit2、无真机）** |

## 关键数字速查

### 公开 test（`tabletennis_ball_racket_v1`，唯一有真 GT 的集）

- overall: P 0.8152 / R 0.7022 / mAP50 0.7361 / mAP50-95 0.2986
- ball: P 0.8676 / R 0.6293 / AP50 0.6595 / AP50-95 0.2536
- racket: P 0.7628 / R 0.7750 / AP50 0.8127 / AP50-95 0.3435

### 最终 ball detector（BNDSTT 人工 GT 36 帧，只读评测）

- **BallTrack**: detection presence 24/36，center error median **8.1 px**，P90 29.0 px
- YOLO ball: detection presence 16/36，center error median 561.2 px（含误检），P90 699.8 px

### 单帧工作点（公开 test，IoU 0.50，one-to-one）

- `base_inference_conf = 0.02`；`ball_conf = 0.05`（fallback）；`racket_conf = 0.30`
- BALANCED ball P/R/F1 = 0.557 / 0.704 / 0.6219
- BALANCED racket P/R/F1 = 0.7897 / 0.7643 / 0.7768

### BNDSTT_30_V1 域内（**只能报 coverage**）

- HIGH_RECALL（ball 0.03 / racket 0.05）: ball 21/30，racket 26/30，both 19/30
- BALANCED（ball 0.05 / racket 0.30）: ball 19/30，racket 17/30，both 8/30

### Temporal（连续视频诊断，**不是 accuracy**）

- RAW candidate coverage 268/324，candidate dropout 12 次（最长 12 帧）
- KALMAN: detector-supported 255，recovered low-conf 8，PREDICTED_ONLY 28，track breaks 7，最长稳定段 44 帧
- SimPLE causal 3 / causal 5: supported 221 / 223，recovered 6 / 8

### 延迟（RTX 4060 Laptop，imgsz 640）

- YOLO ball+racket 39.2 ms | Pose 44.7 ms | Temporal 0.196 ms/帧 | combined serial 83.9 ms（11.9 FPS）
- THEORETICAL ONLY 异步吞吐 22.4 FPS（未实测）

## 已停用 / 已冻结

| 项 | 状态 |
| --- | --- |
| **`BNDSTT_BR_FINETUNE_V1`（80 张 fine-tune pool）** | **SUSPENDED / NOT USED FOR TRAINING**（`human_verified = 0`） |
| `BNDSTT_MANUAL_GT_V1` | 只读；**不得用于训练** |
| `artifacts/quick_test` | **完全冻结，未修改** |
| hand / toss_hand / racket_hand 路线 | **永久取消（DEPRECATED）** |
| 旧 29-image ChatGPT GT 实验 | **DEPRECATED / INVALID FOR FINAL EVALUATION** |
| 8899 标注服务 | 已停止，不再启动 |

## 相关文档

- `FINAL_ARCHITECTURE.md` — 正式架构与不变式
- `MODEL_MANIFEST.md` — 模型交接清单（含 SHA256）
- `config/default_inference.yaml` — 正式推理配置
- `RKNN_DEPLOYMENT_GUIDE.md` — RKNN 部署指南
- `reports/C_FINAL_HANDOFF_V1.md` — 最终完成报告
