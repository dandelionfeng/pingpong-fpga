# 四个球 YOLO 模型 · 队长独立交付包（BALL_YOLO_FOUR_MODELS）

日期：2026-10-21　分支：`codex/c-pc-detector`
交付物：`artifacts/handoff/BALL_YOLO_FOUR_MODELS_FOR_CAPTAIN.zip`

本任务只做**资产整理、完整性核验、统一推理入口、打包**。**没有训练、没有重导、没有做准确率对比、没有排名。**

---

## 1. 四个模型（全部本机核验哈希一致）

| 交付文件名 | 输入 | 大小 | SHA256 | 原始路径 |
| --- | --- | --- | --- | --- |
| `ball_yolo_v1_1280.onnx` | 1280×1280 | 12,218,920 B | `185a337ec9ed6c52e867c3748e889ef8fac56c855ce5cceb478a7213a1f4a17b` | `artifacts/files/models/ball_yolo_v1/ball_yolov8n_gray_1280.onnx` |
| `ball_roboflow_960.onnx` | 960×960 | 12,159,554 B | `7d2da4eb27b07a515551e141fafaa7c3e34253a4498812d2e3da5138e85e3e36` | `artifacts/files/models/ball_rf_v1/ball_rf_v1_960.onnx` |
| `ball_roboflow_1280.onnx` | 1280×1280 | 12,218,920 B | `f5ec1e7a19deada33486ab65bee2f7e251c1594cb9d777eae0d55b2971802d9d` | `artifacts/files/models/ball_rf_v1/ball_rf_v1_1280.onnx` |
| `ball_v6_round2.onnx` | 960×960 | 12,159,554 B | `d32b98d6a5a986b527654a7a34656a96d6d79a2702440bfffb36cf49dd685383` | `artifacts/files/models/ball_fast_v2_scratch/ball_fast_v2_scratch_960.onnx` |

- 四个文件的 SHA256 与任务给出的记录**逐个 MATCH**；复制到包内后再次逐字节比对，**4/4 identical**。
- 输入张量：`[1, 3, S, S]` float32，NCHW；输出：`[1, 5, 33600]`（1280）或 `[1, 5, 18900]`（960）。
  5 = 4 个框参数 + **1 个类别**，即**单类 `ball`**（ONNX 内无 metadata，类别以训练配置为准）。
- 四个模型输入约定相同：**BGR → 灰度 → 三通道复制 → letterbox → /255 → NCHW**（项目统一的 gray3）。
- 未混入 Dryad、外部开源权重、crop 系列、三分类统一模型。目录里另有 `ball_fast_v1_960`、
  `ball_crop_v1/v2`、`ball_mix_v1` 等**已淘汰实验**，均**未**进入交付包。

---

## 2. 包结构

```text
BALL_YOLO_FOUR_MODELS/
├── models/                    4 个 ONNX（逐字节一致）
├── config/model_manifest.json 形状/类别/来源/哈希/一致性/限制
├── tools/eval_ball_models.py  统一推理入口（图片 / 文件夹 / 视频）
├── tools/score_ball_models.py 用自带 GT 打分
├── gt/images/                 42 张 1920×1080 测试图
├── gt/annotations_json/       42 个 GT JSON（ball=0, hand=1, 像素 xyxy）
├── README_CAPTAIN.md
├── MODEL_SHA256.txt
└── THIRD_PARTY_NOTICES.md
```

ZIP 内共 **94 个条目**：4 个 ONNX + 42 图 + 42 JSON + 6 个文档/配置/工具。无缓存、无日志、无 PT、无视频。

---

## 3. 冒烟测试（四个模型独立加载 + 推理，全部通过）

同一批 3 张真实图（1920×1080，来自包内 GT）：

| 模型 | 自动识别的输入 | 有检测帧 | 最高分 | 单帧耗时 |
| --- | --- | --- | --- | --- |
| `ball_yolo_v1_1280` | 1280×1280 | 2/3 | 0.224 | 59 ms |
| `ball_roboflow_960` | 960×960 | 3/3 | 0.507 | 35 ms |
| `ball_roboflow_1280` | 1280×1280 | 3/3 | 0.373 | 60 ms |
| `ball_v6_round2` | 960×960 | 2/3 | 0.291 | 37 ms |

- **输入尺寸由 ONNX 图自动读取**，不是硬编码：960 的模型不会被喂 1280 张量，反之亦然。
- 输出坐标为**原图像素**：例 `[1150.75, 168.93, 1173.59, 194.87]`（1920×1080 图内），
  同时给出归一化坐标；`class_id=0`、`score∈[0,1]`。12 条记录做范围检查，**0 违规**。
- 视频冒烟：`sample_clip.mp4` 40 帧 → 25 帧有检测，产出逐帧 JSONL + 标注后的 mp4。
- 错误路径已验证：模型编号非法/文件缺失/源不存在 → 明确报错 + 非 0 退出码，**不会静默返回空结果**。
- 从**解压后的 ZIP** 再跑一遍：4/4 哈希 MATCH，推理正常（42 帧 28 帧有检测），说明包自包含可用。

耗时随线程数与机器负载波动（同一模型观察到 35–94 ms/帧，`--threads` 未指定且多进程时更慢），
README 已注明延迟是环境相关值。

---

## 4. ZIP

| 项 | 值 |
| --- | --- |
| 绝对路径 | `D:\电脑管家迁移文件\xwechat_files\wxid_ttrefx9qt9o722_32d9\msg\file\2026-10\方案及分工\方案及分工\pingpong-fpga\artifacts\handoff\BALL_YOLO_FOUR_MODELS_FOR_CAPTAIN.zip` |
| 大小 | **67,697,585 B**（约 64.6 MiB） |
| SHA256 | **`19488e6a8361e8c8394da96fc4b9cba1bf66b82f49fafc0802fbb0421071b623`** |

---

## 5. 队长怎么用

```powershell
# 进入解压后的目录
cd BALL_YOLO_FOUR_MODELS

# 单张图 / 整个文件夹
python tools/eval_ball_models.py --model ball_yolo_v1_1280 --source gt\images --out out\v1

# 视频
python tools/eval_ball_models.py --model ball_roboflow_960 --source path\to\clip.mp4 --out out\video

# 自己算准确率（同一匹配规则）
python tools/score_ball_models.py --predictions out\v1\predictions.jsonl --conf 0.10
```

`--model` 只能取四个编号之一；`--conf`（默认 0.10）、`--iou`（0.50）、`--stride`（视频抽帧）可调。

---

## 6. GT 与评测材料

| 项 | 值 |
| --- | --- |
| 图像 | `gt/images/`，42 张，1920×1080 |
| 标注 | `gt/annotations_json/`，42 个 JSON；`objects[].bbox_xyxy` **像素坐标**，`class_name` 区分 `ball`/`hand` |
| 统计 | **42 图 / 36 个有球帧 / 36 个球框 / 6 个空帧** |
| 匹配规则 | 一对一贪心，IoU ≥ 0.5；匹配后球心 ≤ 50 px 记命中；球心误差只统计匹配成功的检测；AP50 用 101 点插值 |
| 原始位置 | `artifacts/files/datasets/BNDSTT_MANUAL_GT_V1/`（images 来自 `artifacts/files/datasets/BNDSTT_MVP_v1/images_color/train/`） |

⚠️ 该 42 图基准在项目内部已被多轮实验使用，**只能作为诊断集**，不能当成"全新独立测试"。

---

## 7. 未完成 / 限制 / 环境

1. **没有做四模型准确率对比**（按任务要求），也没有选胜者。
2. `ball_roboflow_960` 与 `ball_roboflow_1280` 是**同一组权重的两种导出尺寸**，不是两个不同模型；
   分别测可以看出分辨率影响。
3. `ball_yolo_v1_1280` 的 PT 与 ONNX 两条推理路径在项目历史上曾被观察到结果不一致
   （同权重 7/36 vs 15/36，见 `reports/BALL_YOLO_V5_ROBOFLOW_REPORT.md` §4.2）。
   本包给的是 **ONNX**，项目对外引用的 15/36 也是 ONNX 路径的数字。
4. 许可：模型基于 Ultralytics YOLOv8n（**AGPL-3.0**）；后训练模型用到 Roboflow v3（**CC BY 4.0**，
   需署名）。详见包内 `THIRD_PARTY_NOTICES.md`。**对外分发前请确认团队对 AGPL 的接受度。**
5. 依赖：`numpy` / `opencv-python` / `onnxruntime`（CPU 即可），未打进 ZIP。
6. 未提交任何 PT/ONNX/视频/ZIP 到 Git（`artifacts/` 本就忽略）；未推送 main、未合并 PR。
7. 原始模型、C++ 接口、V2.4/V2.3 交付包**均未改动**。
