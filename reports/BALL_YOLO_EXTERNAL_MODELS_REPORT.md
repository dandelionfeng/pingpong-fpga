# 三个开源乒乓球检测模型实测比较（现成权重，不重训）

日期：2026-10-21　分支：`codex/c-pc-detector`　评测集：`BNDSTT_MANUAL_GT_V1`（42 图 / 36 有球 / 6 空帧）

## 0. 结论：**没有胜出者**

三个候选在真实球馆场景都**远低于 V1**（最好的是 C2 的 5/36，V1 为 15/36，BallTrack 为 28/36）。
**不替换正式模型**，继续保留 V1 为 YOLO 候选、BallTrack 为正式球检测后端。

| 排名 | 候选 | imgsz | 命中 50 px | TP/FP/FN | P | R | F1 | AP50 | 中位/P90 误差 | 空帧误检 | CPU 延迟 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **C2** Rahimdzx | **1280** | **5/36** | 5/33/31 | 0.1316 | 0.1389 | 0.1351 | 0.0238 | 2.21 / 3.32 px | 4 框 | 58.7 ms |
| 2 | C2 Rahimdzx | 640 | 2/36 | 2/28/34 | 0.0667 | 0.0556 | 0.0606 | 0.0079 | 3.00 / 3.44 px | 3 框 | 35.8 ms |
| 3 | C1b harounRhim train2 | 1280 | 0/36 | 0/10/36 | 0 | 0 | 0 | 0 | — | 1 框 | 74.9 ms |
| 4 | C1 harounRhim train | 1280 | 0/36 | 0/0/36 | 0 | 0 | 0 | 0 | — | 0 框 | 45.2 ms |
| 5 | C3 SMani24 | 1280 | 0/36 | 0/33/36 | 0 | 0 | 0 | 0 | — | 7 框 | 57.0 ms |
| — | **V1（本项目现行）** | 1280 | **15/36** | 15/48/21 | **0.2381** | **0.4167** | **0.3030** | **0.2282** | **2.41 / 5.02 px** | 6 框 | 73.4 ms |
| — | BallTrack（参考） | — | **28/36** | — | — | — | — | — | 7.96 / 24.86 px | — | 190 ms |

（表内为统一口径 conf=0.10；C1/C1b 在 640 也是 0/36，见 §4 明细。）

---

## 1. 权重来源与元数据

| 候选 | 实际使用的文件 | 大小 | SHA256 | 类别 | 训练 imgsz | 许可 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | `runs/detect/train/weights/best.pt`（从 Release 归档 `pingpong-v0-archive.zip` 内提取） | 6,220,714 B | `66642bee0d9fc036dabb26daeba5de3547e72776430f78a099abdf46756e12d5` | 3 类：`pingpong_ball` / `paddle` / `table` | 640 | 仓库 **MIT** |
| C1b | `runs/detect/train2/weights/best.pt`（同一归档） | 18,437,667 B | `f012e2f7290e942acc1852998d44d02991f9b82d4bf1d1a79bc39d7c83f314b3` | 3 类（无名字，按 0/1/2） | 640 | 同 C1 |
| C1-误 | Release 资产 `yolov8n.pt` | 6,549,796 B | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` | **COCO 80 类**（`sports ball`=32） | 640 | — |
| C2 | `Models/detect/ball_detector/weights/best.pt` | 6,226,026 B | `afbd7d1c11d094d39b9fe36a626a30bcbf978bec9b097f70fe953cdc3c0154de` | 1 类：`ball` | 640 | 仓库**无 LICENSE 文件** |
| C3 | `yolov8_ping_pong.pt` | 6,217,902 B | `fb2f580f604961c94ae779ab9cf198d5f8b208b83f70d35be476c8ec7432af83` | 2 类：`orange_ping_pong_ball` / `moving_orange_ping_pong_ball` | 640 | 仓库**无 LICENSE 文件** |

**两点必须说明的发现**：

1. **C1 的 Release 里名为 `yolov8n.pt` 的资产并不是训练好的乒乓球模型**，而是 COCO 通用预训练权重
   （80 类）。真正的乒乓球权重在 280 MB 的 `pingpong-v0-archive.zip` 里（`runs/detect/train*`），
   我把两套都提取并评测了。若只看 release 列表直接下 `yolov8n.pt`，会误以为"该模型不工作"。
2. **C2、C3 仓库没有 LICENSE 文件**（GitHub license=none）。按项目规则，来源不明许可的权重
   **不能进入交付**，即使精度达标也只能作研究对照。C1 为 MIT，可再分发。

---

## 2. 评测方法（三者与 V1 完全同一口径）

- **同一批图像、同一份 GT、同一个评分器**：`tmp/eval_external.py` 复用 `eval_ball_bndstt.py`
  的 `load_gt()` 与 `score_detector()`；IoU 0.5 匹配、球心 ≤50 px 记为命中、球心误差只统计匹配成功的检测。
- **各自的预处理**：候选模型用**原始彩色图**（它们都在彩色图上训练），在各自推理尺寸下预测；
  V1 的基线数字来自它自己的灰度三通道 + 1280 预处理（历史一致）。没有把候选强行改成灰度或 ONNX。
- **类别映射**：每个模型只保留"球"的类别（C1/C1b → 0；C2 → 0；C3 → 0 与 1，因为
  `moving_orange_ping_pong_ball` 也是球）。
- **阈值为固定 conf=0.10**（任务指定）。另外给出了 conf=0.05 的信息性数字，**没有用测试集调阈值**。
- **先验证"确实输出球框"**：每轮都统计"42 帧里有球类检测框的帧数"，C1 为 0/42（说明不是评分问题，
  而是模型根本不出框）。

---

## 3. 为什么三个都失败（与项目已有结论一致）

1. **尺度不匹配**：BNDSTT 是 1920×1080 远景，球 25–67 px；三个候选都在 640 的近景/转播画面训练
   （球通常 30–100 px）。在 640 输入下 BNDSTT 的球只有 8–22 px，几乎低于它们的可见极限。
   把输入提到 1280 后 C2 从 2/36 升到 5/36，方向对但没有质变。
2. **颜色域**：C3 只认**橙色**球（两个类名都带 orange），BNDSTT 是白色球 → 0 命中，
   但它仍会在背景上出 33 个误检框（说明它在"找橙色物体"）。
3. **C1 的球类几乎不出框**：42 帧里 0 个球框（两套权重、两个尺寸都是），它的训练数据里球太大、
   场景差异过大；增加输入尺寸只让它多出 10 个误检而不是命中。
4. **这不是评分器问题**：同一评分器下 V1 能拿到 15/36，说明评分链本身正常。

---

## 4. 明细（conf 0.10 / 0.05）

| 候选 | imgsz | conf | 命中 | TP/FP/FN | P | R | F1 | AP50 | 中位/P90 | 空帧误检 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 train | 640 | 0.10 | 0/36 | 0/0/36 | 0 | 0 | 0 | 0 | — | 0 |
| C1 train | 640 | 0.05 | 0/36 | 0/0/36 | 0 | 0 | 0 | 0 | — | 0 |
| C1 train | 1280 | 0.10 | 0/36 | 0/0/36 | 0 | 0 | 0 | 0 | — | 0 |
| C1b train2 | 640 | 0.10 | 0/36 | 0/0/36 | 0 | 0 | 0 | 0 | — | 0 |
| C1b train2 | 1280 | 0.10 | 0/36 | 0/10/36 | 0 | 0 | 0 | 0 | — | 1 |
| C2 | 640 | 0.05 | 3/36 | 3/31/33 | 0.0882 | 0.0833 | 0.0857 | 0.0103 | 2.45 / 3.33 | 3 |
| C2 | 1280 | 0.10 | **5/36** | 5/33/31 | 0.1316 | 0.1389 | 0.1351 | 0.0238 | 2.21 / 3.32 | 4 |
| C3 | 640 | 0.05 | 0/36 | 0/10/36 | 0 | 0 | 0 | 0 | — | 3 |
| C3 | 1280 | 0.05 | 0/36 | 0/33/36 | 0 | 0 | 0 | 0 | — | 7 |

GPU 端到端耗时（42 帧，含取图与解码）：C1 0.26–0.30 s/帧、C2 0.28–0.32 s/帧、C3 0.27–0.36 s/帧。

---

## 5. 自动选择结果

按"优先看真实命中率与 Recall，其次误检/F1/定位/速度"排序：

1. **C2（Rahimdzx，1280）= 5/36** —— 三个里最好，仍只有 V1 的三分之一；
2. C3 = 0/36（只认橙色球）；
3. C1 / C1b = 0/36（不出球框）。

**没有候选优于 V1（15/36、F1 0.3030、AP50 0.2282），因此没有胜出者，不采用。**
另外 C2/C3 无许可证文件，即便精度达标也不能进交付。

---

## 6. 交付保护

| 约束 | 状态 |
| --- | --- |
| 未训练新模型 | ✅ 只加载现成权重做前向 |
| 未替换正式模型 | ✅ V1 权重/ONNX 未动（`f2dc54ec…`） |
| 未改 V2.4 ZIP | ✅ |
| 未改 C++ 接口 | ✅ |
| 未推送未验证模型 | ✅ |
| 只装了 `dill` 这一个依赖 | ✅ C3 的 checkpoint 需要它才能反序列化；仅在本机 venv，无其他环境改动 |
| 未运行仓库里的安装/训练脚本 | ✅ 只下载权重文件 |

---

## 7. 复现命令

```powershell
# 下载（已保存到 artifacts/files/models/external_candidates/）
curl.exe -L --proxy http://127.0.0.1:7890 -o C1_release.zip `
  https://github.com/harounRhim/pingpong-detection-yolov8/releases/download/v0-archive/pingpong-v0-archive.zip
# 归档内提取 runs/detect/train/weights/best.pt 与 runs/detect/train2/weights/best.pt
curl.exe -L -o C2_Rahimdzx_best.pt `
  https://raw.githubusercontent.com/Rahimdzx/table-tennis-ball-detection/master/Models/detect/ball_detector/weights/best.pt
curl.exe -L -o C3_SMani24_yolov8_ping_pong.pt `
  https://raw.githubusercontent.com/SMani24/Ball-detection-with-Yolov8/main/yolov8_ping_pong.pt

# 统一评分（每模型单独一次，conf 0.10 为决策阈值）
.\.venv\c-detector\Scripts\python.exe tmp\eval_external.py `
  --weights artifacts\files\models\external_candidates\C2_Rahimdzx_best.pt `
  --tag C2_Rahimdzx_i1280 --ball-classes 0 --imgsz 1280
```

记录：`artifacts/files/reports/EXTERNAL_CANDIDATES/*.json`（每个候选一份，含阈值明细与延迟）。

---

## 8. 对下一步的意义

三个公开模型都没有解决"远景小球"这个问题，和本项目自己的实验结论一致：
**瓶颈在目标域数据与球的像素尺度，不在模型选择。** 现有 V1（15/36）仍是本项目最好的 YOLO，
BallTrack（28/36）仍是正式后端。若要继续提升，最有效的仍是扩充目标域标注/伪标签（多片段），
而不是换用公开权重。
