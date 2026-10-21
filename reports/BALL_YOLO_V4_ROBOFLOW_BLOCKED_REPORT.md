# 球检测第四轮（Roboflow 新数据集）：下载受阻 + 伪标签审计 + 混合微调实验

日期：2026-10-21　分支：`codex/c-pc-detector`　上轮：[BALL_YOLO_V3_DRYAD_REPORT](BALL_YOLO_V3_DRYAD_REPORT.md)

## 0. 结论

**本轮要求的 Roboflow 数据集无法下载（缺 API Key + 网页被 Cloudflare 403），因此 B/C 两组的
原计划实验无法执行。** 在可用数据内做了替代实验：审计已有 BNDSTT 伪标签 + 用新片段伪标签
扩充后混合微调。结果：**召回略升（17/36 vs 15/36），但误检翻 3 倍（161 vs 48），F1 从 0.303
掉到 0.159 → 不予采用。**

- 正式 ball 后端仍是 **BallTrack（28/36）**。
- 现有 V1 模型仍是本项目最好的 YOLO ball 模型（15/36）。
- **未覆盖原始模型、未改 V2.4 包、未改 C++ 接口、未推送 main、未训练其他类别。**
- 未导出的"交付"ONNX；本轮唯一的新 ONNX 在 `ball_mix_eval_only/`，**仅用于评测**。

---

## 1. Roboflow 下载：真实失败记录

| 通道 | 结果 |
| --- | --- |
| `https://universe.roboflow.com/pingpong-ojuhj/ping-pong-detection-0guzq` | **HTTP 403**（直连、走代理、带浏览器 UA 均 403，Cloudflare 拦截） |
| `.../dataset/{1,2}/download/yolov8` | **HTTP 403** |
| `https://api.roboflow.com/pingpong-ojuhj/ping-pong-detection-0guzq` | **HTTP 401**（端点可达，缺鉴权） |
| 本机凭据 | `ROBOFLOW_API_KEY` / `ROBOFLOW_KEY` / `RF_API_KEY` 均未设置；`~/.roboflow`、`~/.config/roboflow`、`%APPDATA%\roboflow` 均不存在；仓库内无密钥文件（历史 `vision/c_perception_v2` 只从环境变量读取，从未落盘） |
| 镜像 | 检索无该数据集（`ping-pong-detection-0guzq`）的 HuggingFace/Kaggle 镜像；其他同名 ping-pong 数据集同样在 Roboflow 墙后 |

**解除阻塞的确切条件（二选一）**：

1. 在本机设置 `ROBOFLOW_API_KEY`（Roboflow 账号 → Settings → API Keys），然后执行
   ```powershell
   $env:ROBOFLOW_API_KEY = '<key>'   # 只在当前会话，不写进任何文件
   .\.venv\c-detector\Scripts\python.exe -c "from roboflow import Roboflow; rf=Roboflow(api_key=__import__('os').environ['ROBOFLOW_API_KEY']); p=rf.workspace('pingpong-ojuhj').project('ping-pong-detection-0guzq'); p.version(<版本号>).download('yolov8', location='artifacts/files/datasets/roboflow_pp')"
   ```
2. 或在 Roboflow 页面手动导出 YOLOv8 zip，放到 `artifacts/files/datasets/roboflow_pp/` 下，我直接审计。

版本号也需要确认（页面 403 看不到）。拿到 key 后我用 `rf.workspace(...).project(...).versions()` 列出全部版本及其划分与许可。

**因此 §2 之后的内容是本轮在现有数据上能做的替代工作**，不代表 Roboflow 数据已评估。

---

## 2. 已有伪标签质量审计（本轮实际完成）

`artifacts/files/reports/PSEUDO_AUDIT/pseudo_audit.json`

| 伪标签集合 | 图像 | 球框宽中位（1920 等效） | p10/p90 | 框内-框外亮度差 中位 | 亮度差 < 0 的框 | 片段数 | 相邻帧对数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **V1 使用的 521 张** | 521 | 26.3 px | 22.5 / 30.0 | **+30.4** | **0** | **11** | **510** |
| ball_pseudo_v2 残留 291 张 | 291 | 26.3 px | 18.8 / 30.0 | +13.0 | **90** | 15 | 260 |
| 人工 GT（对照） | 36 | 34.3 px | — | — | — | — | — |

三个结论：

1. **V1 的 521 张伪标签质量可靠**：全部落在比周围亮的球状斑块上（亮度差中位 +30，无负数），
   尺寸分布集中（22–30 px），与人工 GT 的 34.3 px 同量级。
2. **但多样性严重被高估**：521 张只来自 **11 个片段**，其中 **510 对是相邻帧**（同一段视频的连续帧）。
   也就是说真正独立的场景只有约 11 个。这正是"多轮训练后仍未覆盖其他 session"的结构性原因。
3. **残留的 291 张里有 90 张亮度差为负**（框比周围暗，是热图伪影），不能直接用；
   应用与 V1 构建时相同的亮度对比度 QC 后 **只剩 167 张**（剔除 124 张，剔除率 43%）。

BNDSTT 测试 session 隔离复核：三个生成日志中**没有任何一行**提到 5 个测试 session（规则是
生成器按名字硬排除），与代码一致。

---

## 3. 替代实验：V1 + 新片段伪标签混合微调

| 项 | 值 |
| --- | --- |
| 数据集 `ball_mix_v1` | V1 训练集 2,738 张 + **167 张**通过 QC 的新片段伪标签 = **2,905 张**；验证集保持 Match5（180 张，未参与训练） |
| 唯一变化 | 增加目标域覆盖（新片段），其余配置与 V1 完全一致 |
| 训练 | warm start 自 `ball_yolo_v1/best.pt`，yolov8n，1280，5 轮，lr0 0.0015，无 mosaic，seed 42 |
| 耗时 / 权重 | ≈ 12 min；`ball_mix_v1/weights/best.pt` SHA256 `2c2a17120f8d510d0280fedf1b0a4962cdc8dd095403140d44e3264bfefd64dc` |
| 验证集（tabletennis Match5） | mAP50 **0.1031**（V1 原值 0.1157，未提升） |

### 3.1 冻结 BNDSTT 诊断（唯一一次，统一 ONNX 评分器）

| conf | 命中 | TP/FP/FN | P | R | F1 | AP50 | 中位/P90 误差 | 空帧误检 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.05 | **20/36** | 20/311/16 | 0.0604 | 0.5556 | 0.1090 | 0.1793 | 3.83 / 6.59 px | 20 框 |
| 0.10 | **17/36** | 17/161/19 | 0.0955 | 0.4722 | 0.1589 | 0.1734 | 3.82 / 6.95 px | 11 框 |
| **0.15** | **17/36** | 17/101/19 | 0.1441 | 0.4722 | 0.2208 | 0.1734 | 3.82 / 6.95 px | 4 框 |
| 0.25 | 10/36 | 10/30/26 | 0.2500 | 0.2778 | 0.2632 | 0.1254 | 4.08 / 6.60 px | 0 框 |

对照（同口径，历轮已测）：**V1 = 15/36，TP/FP/FN 15/48/21，P 0.2381，R 0.4167，F1 0.3030，
AP50 0.2282，中位 2.41 / P90 5.02 px，空帧 6 框**。

### 3.2 判定：不采用

- **召回**：确实上升（15 → 17 命中，conf 0.10/0.15），但只在"多出大量误检"的前提下成立。
- **精度**：P 从 0.2381 掉到 0.1441（最优工作点），FP 从 48 涨到 101，空帧误检 6 → 4~11 框。
- **F1**：0.3030 → 最该工作点 0.2208，**更差**。AP50 也从 0.2282 降到 0.1734。
- 也就是说：**这是"用误检换召回"的典型退化**，不符合"提升检出率同时控制误检"的要求，不导出交付 ONNX。

### 3.3 失败原因

1. 新增的 167 张伪标签虽然过了亮度 QC，但亮度差中位只有 +13（V1 那批是 +30），框仍偏松；
   模型学到"更爱开火"，于是误检暴涨。
2. 数据量仍然太小（+167 张，约 +6%），不足以改变域覆盖，却足以破坏原模型的置信度阈值分布
   （这与此前 Dryad 微调观察到的"微调即扰动"是同一现象）。
3. 目标域真正的瓶颈仍是**独立片段太少**（11 段），扩充 167 张只增加了少量片段。

---

## 4. 未执行项（如实）

| 项 | 状态 | 原因 |
| --- | --- | --- |
| Roboflow 数据下载与审计 | **未执行** | 403 / 401，缺 API Key（见 §1） |
| B 组：Roboflow 单数据源训练 | 未执行 | 同上 |
| C 组：V1+Roboflow+BNDSTT 伪标签混合 | 未执行 | 同上；用"V1+新伪标签"做了近似替代 |
| 高分辨率（1536/1600）方案 | 未执行 | 时间预算用在了替代实验；且上轮裁剪实验表明"仅提高分辨率"不能跨域迁移 |
| C++ 推理验证 | 未执行 | 无达标候选（本就不应导出） |

---

## 5. 交付判定

| 约束 | 状态 |
| --- | --- |
| 只有真实域优于 V1 才导出交付 ONNX | ✅ 未达标 → 未导出（`ball_mix_eval_only/` 为评测专用） |
| 不覆盖原始模型 | ✅ `ball_yolo_v1/weights/best.pt` 未改动（`f2dc54ec…`） |
| 不修改 V2.4 交付包 | ✅ ZIP 哈希仍 `7edf80ed…` |
| 不改 C++ 对外接口、不训练其他类别 | ✅ |
| BallTrack 保留为正式后端 | ✅ |
| 密钥不落代码/仓库 | ✅ 全程未写入任何文件 |

---

## 6. 下一步（需要你的一个决定）

1. **给 API Key 或手动导出 zip** → 我立刻执行真正的 B/C 对照（Roboflow 9,607 张 YOLOv8 格式）。
   这是本轮唯一缺的东西，不是方法问题。
2. 拿到数据后的实验设计（已就绪）：
   - B：Roboflow 单独微调（短周期，5–8 轮）；
   - C：V1 数据 + Roboflow（按 1:1~1:2 采样）+ 521 张 BNDSTT 伪标签 + 239 负样本；
   - 均以 1280 为主，同时跑一版 1536 对比"小球高分辨率"假设；
   - 统一 ONNX 评分器、同一匹配规则、BNDSTT 只做诊断。
3. 若你想先要"纯提升"而不引入新数据：可以尝试**把 11 个片段扩到 30+ 个片段**（跑完剩余非测试
   session 的 BallTrack 伪标签，约 2.5 h CPU 独占）——这是当前数据下唯一能真正增加域覆盖的手段。

---

## 7. 复现命令

```powershell
# 伪标签审计 + QC
.\.venv\c-detector\Scripts\python.exe tmp\audit_pseudo_labels.py
.\.venv\c-detector\Scripts\python.exe tmp\qc_pseudo_v2.py

# 混合数据集与微调（warm start 自 V1，1280，5 轮）
.\.venv\c-detector\Scripts\python.exe tmp\build_ball_mix.py
#   训练命令行见 artifacts\runs\train_ball_mix.log

# 评测（导出仅用于评测的 ONNX，再用统一评分器）
D:\Python\python.exe -c "..."   # 见 §3 导出片段
.\.venv\c-detector\Scripts\python.exe tmp\eval_ball_onepass.py `
  --onnx artifacts\files\models\ball_mix_eval_only\ball_mix_v1_1280.onnx `
  --dataset bndstt --mode full --tag ball_mix_v1_bndstt
```

记录：`artifacts/files/reports/BALL_YOLO_V2/onepass_ball_mix_v1_bndstt.json`、
`artifacts/files/reports/PSEUDO_AUDIT/{pseudo_audit.json,pseudo_v2_qc.json}`。
