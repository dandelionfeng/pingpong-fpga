> ## ⚠️ DEPRECATED / LEGACY（2026-10-13）
>
> 本目录是**历史工具与旧 MVP 链路**，**不是当前正式 C pipeline**。
>
> - 类别 `1 hand` 已**永久取消**（不训练 hand / toss_hand / racket_hand）；
> - 其中的 29-image ChatGPT curated GT 已被判定**语义有误**，
>   `29/29 PASS` 只代表流程自洽，**不代表标注正确**；
> - 其中的手工标注工具仅作为**历史工具**保留；
>   `artifacts/files/datasets/BNDSTT_MANUAL_GT_V1` 的数据**只允许只读使用**，
>   **不得用于训练**（当前 `human_verified` 用途仅限于 ball benchmark 的评测集）。
>
> 当前正式架构见 `vision/c_perception_v2/FINAL_ARCHITECTURE.md`。

# BNDSTT 纯人工标注工具 — MANUAL_GT_V1

这个工具**只做一件事**：让你自己在原图上用鼠标画 bbox。

**它不会替你判断目标位置。** 打开任何一张图，画面都是**空的（0 个框）**，
除非这张图是你自己在这个工具里保存过的。

页面上永久显示 `AUTO PROPOSALS DISABLED IN MANUAL_GT_V1`。
所有旧数据（DeepSeek 80 张、ChatGPT 29 张、proposal、pose/skin/template 框、旧 YOLO 标签、
模型预测）都**视为历史参考，绝不加载**。

---

## 1. 如何启动（一个命令）

```powershell
powershell -ExecutionPolicy Bypass -File vision\bndstt_mvp\start_manual_annotation.ps1
```

等价的手工命令：

```powershell
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\manual_annotation_server.py
```

启动后终端会打印浏览器地址。

## 2. 浏览器地址

默认：**http://127.0.0.1:8765**

如果 8765 被占用，脚本会自动往后找端口，并在终端明确打印最终地址（例如 `http://127.0.0.1:8766`）。

## 3. 三个类别（永久固定，不能改）

| id | 名称 | 颜色 |
| --- | --- | --- |
| 0 | ball | 红 |
| 1 | hand | 绿 |
| 2 | racket | 橙 |

不要加 release / apex / contact / legal / player 等类别。

## 4. 快捷键

| 键 | 作用 |
| --- | --- |
| `0` `1` `2` | 选择 ball / hand / racket（新画的框用当前类别） |
| 鼠标拖动空白处 | 画新框 |
| 点击框 / 点右侧列表 | 选中 |
| 拖动框内部 | 移动 |
| 拖动框的 8 个白点 | 缩放（resize） |
| `Delete` / `Backspace` | 删除选中的框 |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做 |
| `Ctrl+S` | 只保存 |
| `S` | 保存并进入下一张 |
| `←` / `→` | 上一张 / 下一张 |
| `+` / `-` / `R` | 放大 / 缩小 / 重置缩放 |
| 滚轮 | 以光标为中心缩放 |
| `Space`+拖动 或 中键拖动 | 平移 |
| `G` | 彩色 / 灰度显示切换 |
| `E` | 标记「空图已人工确认」 |
| `N` | 标记 NEEDS_REVIEW |
| `Q` | QA 模式（只能看，不能改） |
| `F` | 全屏 |

## 5. ball 规则

只标**当前发球动作中的乒乓球**。

- 看得见 → 标；很小但明确 → 标。
- 运动模糊但能确认 → 标整块可见的模糊区域。
- 部分被手/拍遮住但位置明确 → 标可见部分。
- **完全看不清就不要猜**，按 `N` 标 NEEDS_REVIEW。

绝对不能标成 ball 的东西：墙上白点、灯、窗帘亮点、**球衣上的 white logo**、
海报文字、球网反光、球台白线、地板反光、地上的球。

bbox 尽量 tight。

## 6. hand 规则

标**发球队员自己可见的手**。

- 两只手都清楚 → 画两个 hand 框。
- 框包含手掌 + 手指，到腕部附近结束。
- **不要把整条前臂、整条胳膊、身体、脸一起框进去。**
- 一只手完全看不见 → 不用强行标。
- 不要标背景里其他运动员的手。

## 7. racket 规则

只标**发球队员真正的乒乓球拍**。

- 框尽量包含拍面 + 可见拍柄。
- 不要带进大量手 / 胳膊 / 身体。
- 严禁把球台、球网、网架、墙、桌角、背景器材当成 racket。
- 这一帧球拍完全看不见 → 这一帧就没有 racket 标签，**不要硬凑**。

**一张图可以只有 ball、只有 hand、或者一个框都没有。**
数量正确 > 类别齐全。

## 8. prev / next / crop 怎么用

右侧三张参考图：

- `PREV` / `NEXT`：同一 session 内前后相邻帧，用来判断小白点是否沿合理轨迹移动、
  以及判断哪个人是当前发球队员。
- `CROP REFERENCE`：放大的参考图。

**参考图全部只读。只有左边的大图（CURRENT）能画框，也只有它的坐标是正式坐标。**
绝对不要把 crop 图上的位置换算回主图 —— 以前就是这样出错的。

## 9. 如何保存

- `S` = 保存并下一张：会校验 bbox → 写 canonical JSON → 生成 YOLO txt → **从磁盘重新读回**
  → 重新渲染 → 状态变 MANUAL_REVIEWED → 更新 manifest → 才进入下一张。
- `Ctrl+S` = 只保存，不跳转。
- **保存失败会明确弹 `SAVE FAILED`，并且不会跳到下一张。**
- 保存后如果重新读回的框和你画的位置差了超过 1 像素，会弹 ERROR 并停下（说明坐标转换有问题）。

## 10. NEEDS_REVIEW

看不清球、或不确定该标哪个人的时候，按 `N`：

- 该图标记为 `NEEDS_REVIEW` 并保存。
- 在左侧过滤器选 `NEEDS_REVIEW` 可以专门回来处理。
- **NEEDS_REVIEW 的图永远不会进入最终训练数据**，finalize 会拦住它。

## 11. 如何恢复进度

进度实时写在磁盘上：

```
artifacts/files/datasets/BNDSTT_MANUAL_GT_V1/manifests/manual_annotation_manifest.csv
```

关浏览器、关服务器、甚至重启电脑都没关系：

1. 重新启动工具。
2. 点左侧 **Continue from first UNLABELED**，直接跳到第一张没标完的图。
3. 也可以在下拉框里选 `UNLABELED` / `NEEDS_REVIEW` / `TRAIN` / `VAL` 过滤后浏览。

每标完 20 张会自动留一个 `checkpoint_020.csv`、`checkpoint_040.csv` … 快照。
每次保存还会把上一版 JSON 存进 `history/<image_id>/<时间戳>.json`，误操作可以找回。

## 12. QA 模式

按 `Q` 进入 QA 模式：

- bbox 变成只读，不能画也不能改。
- 用来快速回看已保存的框。
- 配合过滤 `MANUAL_REVIEWED` 逐张二次确认。

生成 QA 联系表（只用于看，不能从联系表改坐标）：

```powershell
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\render_manual_gt.py --recent 20
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\render_manual_gt.py --random 50 --seed 7
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\render_manual_gt.py --all
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\render_manual_gt.py --needs-review
```

结果保存在 `artifacts/files/datasets/BNDSTT_MANUAL_GT_V1/qa/`。

## 13. 最终 finalize

**只有 280 / 280 全部是 `MANUAL_REVIEWED`、且 NEEDS_REVIEW = 0 时才允许。**

先只检查（不导出）：

```powershell
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\finalize_manual_gt.py --check
```

检查通过后导出训练数据：

```powershell
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\finalize_manual_gt.py --export
```

finalize 会检查：JSON 数量、YOLO txt 数量、class id、bbox 越界、零面积、NaN、重复框、
图像/标签配对、train/val split、session 泄漏、重复图片、JSON→YOLO→JSON 往返误差。
任何一项不过 → **FINALIZATION FAIL**，不会导出。

导出结果：

```
artifacts/files/datasets/BNDSTT_MANUAL_GT_V1/exports/BNDSTT_YOLO_MANUAL_V1/
    images/train|val/     gray3 PNG
    labels/train|val/     YOLO txt
    dataset.yaml          path 使用绝对路径
```

## 14. 数据目录结构

```
artifacts/files/datasets/BNDSTT_MANUAL_GT_V1/
    annotations_json/     <image_id>.json   人工正式标注（annotation_source = HUMAN_MANUAL）
    labels_yolo/          <image_id>.txt    自动同步生成的 YOLO 标签
    manifests/            manual_annotation_manifest.csv, checkpoint_*.csv, audit_report.json
    history/              <image_id>/<时间戳>.json
    qa/                   联系表与 QA 记录
    exports/              finalize 之后的训练集
```

## 15. 坐标系统（最重要）

- 正式、唯一的坐标 = **current_origin 原图像素 XYXY**。
- 原图 1920×1080 时：`0 <= x1 < x2 <= 1920`、`0 <= y1 < y2 <= 1080`。
- 如果某张图实际尺寸不同，以该图真实的 `naturalWidth/naturalHeight` 为准（页面顶部会显示）。
- 缩放、平移只影响显示；保存时统一换算回原图坐标。
- 换算函数集中在 `manual_web/coords.mjs`，并有自动测试：

```powershell
node tests\test_manual_coords.mjs
```

覆盖：原图↔显示映射、1×/2×/4×/8×/16× 缩放、平移与钳制、bbox 画框/反向拖动、
八个方向的 resize、显示↔原图往返误差 < 1 像素、YOLO 归一化往返 <= 1 像素。

## 16. 本阶段不做的事

不训练 YOLO、不做 overfit 诊断、不做 quick_test、不导出 ONNX / RKNN、不动 RK3576。
工具做好后交给你，由你本人完成 280 张手工标注。
