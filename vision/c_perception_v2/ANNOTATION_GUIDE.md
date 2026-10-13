# BR FINETUNE 标注指南（80 张，2 类）

本文件是**你**（人工）需要执行的那一步说明。机器已经做完的事：

1. 从 BNDSTT 280 帧中**确定性**选出 80 帧（排除 frozen benchmark 与 quick_test）；
2. 用 baseline `best.pt` 以 `conf=0.10` 预标出 ball / racket 候选框；
3. 起好标注服务。

## 启动

```powershell
.\.venv\c-detector\Scripts\python.exe vision\c_perception_v2\annotator_br.py --port 8899
```

浏览器打开 http://127.0.0.1:8899/

界面说明：

- 左侧是图，框上带类别与尺寸；橙色 = ball，绿色 = racket；
- 右侧是 80 张待办列表，已确认的显示绿色「已确认」；
- 紫色「有旧标签」表示这张在旧的 42 张人工标签里出现过（**仍需你重新确认**）。

## 只做四件事

1. **删除误框**：点选框 → `Del`；
2. **移动框**：拖框内部；
3. **resize**：拖框角上的白色方块；
4. **补漏框**：`1` 加 ball、`2` 加 racket，或直接在空白处拖拽画框（默认 ball，画完按 `2` 可切 racket 需重画）。

快捷键：`A` 上一张 / `D` 下一张 / `S` 或 `Enter` 保存并跳下一张未确认 / `F` 适应窗口 / `1` `2` 加框 / `Del` 删框。

## 标注规则（必须遵守）

**ball**

- 只标**当前发球的那颗球**；
- 有运动模糊时，标**整个可见球体/模糊拖影区域**（把拖影一起框进去）；
- 看不清就不要猜——宁可**不标**（留空）。

**racket**

- 只标**当前发球队员的球拍**；
- 框住**拍面 + 可见拍柄**；
- **不标**：对手球拍、背景里的其它球拍、桌角、球网、其它器材。

## 保存语义

点保存后该图变为 `annotation_source = HUMAN_VERIFIED`，**只有这个状态能进入训练**。
baseline 的 proposals 永远是 `MODEL_PROPOSAL`，不会自动变成 GT。

未确认的图可以随时用 `vision\c_perception_v2\finetune_domain.py status` 查看进度。

## 确认完后一条命令跑完

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"

# 1) 构建数据集（会校验 80 张全部 HUMAN_VERIFIED，否则拒绝）
& $python vision\c_perception_v2\finetune_domain.py build

# 2) 训练两个变体：A BNDSTT-only / B mixed replay（公开数据占 30%）
& $python vision\c_perception_v2\train_finetune.py --variant both

# 3) 三模型三处对比 + 阈值扫描 + 两套 contact sheet
& $python vision\c_perception_v2\eval_finetune.py
```

## 门槛（第 14 条）

| 项 | 目标 |
| --- | --- |
| ball 帧检出 | >= 24 / 30 |
| racket 帧检出 | >= 26 / 30 |
| both 帧检出 | >= 22 / 30 |

达不到就不宣称完成——`eval_finetune.py` 会给出 `all_pass: YES/NO` 并列出漏检分析。

## 关于旧 42 张人工标签

它们**不会**自动进入训练：

- 里面有旧的 `hand` 语义（54 个 hand 框），本阶段一律丢弃；
- ball 框规则（是否含拖影）可能与新规则不同；
- 因此只能作为 11 张重合图的**参考**，必须在新 UI 里重新确认。