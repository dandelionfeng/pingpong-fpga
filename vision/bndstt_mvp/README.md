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

# BNDSTT YOLOv8n MVP v1

`PROTOTYPE / MVP` 检测链路入口。类别固定为：

```text
0 ball
1 hand
2 racket
```

本目录只做一件事：把 **ChatGPT curated GT v1**（29 张高置信度标注）走完整条 C 端链路——
严格门禁 → gray3 数据集 → JSON→YOLO 标签 → 单次正式 GPU 训练 → val 评估 → held-out 视频定性测试。

模型定位始终是 `PROTOTYPE / MVP`，**不是竞赛最终模型**。本轮结果见 `reports/C_DETECTOR_MVP_V1.md`。

原始 BNDSTT 视频不会被改写；训练图像、权重、日志、预测图和视频全部落在被 Git 忽略的
`artifacts/files/` 与 `artifacts/runs/`、`artifacts/quick_test/` 下。

## 输入 GT（唯一允许来源）

把 SHA256 为 `ff24236cb69e700640cc9b342ed83e939edebe4c25b72d8c2e1226f4316882eb`
的 `CHATGPT_BNDSTT_MVP_GT_V1.zip` 解压到：

```text
artifacts/files/datasets/BNDSTT_MVP_v1/chatgpt_curated_gt_v1/
```

本目录的代码**只读取 `curated_manifest.csv` 中列出的 29 个 packet**，不会扫描
`deepseek_annotation/outputs/`，因此旧的 DeepSeek 标签 / proposal / pose / skin 框
都不可能混入 MVP 数据集。固定统计（门禁）：

| split | images | ball | hand | racket |
| --- | --- | --- | --- | --- |
| train | 23 | 21 | 31 | 7 |
| val | 6 | 6 | 10 | 4 |
| total | 29 | 27 | 41 | 11 |

## 四个入口

正式训练只允许用 `.venv\c-detector` 里的 CUDA 解释器。

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"

# 1) 门禁：schema / 边界 / 重复框 / split 与类别统计（必须 VALIDATE PASS）
& $python vision\bndstt_mvp\curated_gt.py validate

# 2) 逐张视觉 QA：把正式 bbox 画回原始 current_origin.jpg（29/29 都要看）
& $python vision\bndstt_mvp\curated_gt.py qa --out-dir artifacts\runs\bndstt_yolov8n_mvp_v1\qa

# 3) 构建 gray3 数据集（原尺寸 1920x1080 PNG，R==G==B，坐标不变）
& $python vision\bndstt_mvp\curated_gt.py build --out artifacts\files\datasets\BNDSTT_YOLO_MVP_V1

# 4) 标签回环：YOLO txt → 像素框 → 画回 gray3（必须 ROUND TRIP PASS）
& $python vision\bndstt_mvp\curated_gt.py roundtrip `
    --dataset artifacts\files\datasets\BNDSTT_YOLO_MVP_V1 `
    --out-dir artifacts\runs\bndstt_yolov8n_mvp_v1\roundtrip

# 5) 单次正式训练（25 epochs，参数已固化，不做超参搜索）
& $python vision\bndstt_mvp\train_mvp.py

# 6) val 指标 + 预测预览
& $python vision\bndstt_mvp\validate_mvp.py `
    --weights artifacts\runs\bndstt_yolov8n_mvp_v1\weights\best.pt `
    --out artifacts\runs\bndstt_yolov8n_mvp_v1\validation

# 7) held-out 定性测试（manifest 里 frozen 的 5 个 quick_test 视频，conf 0.20 / iou 0.50）
& $python vision\bndstt_mvp\quick_test_mvp.py `
    --weights artifacts\runs\bndstt_yolov8n_mvp_v1\weights\best.pt `
    --out artifacts\quick_test\bndstt_yolov8n_mvp_v1
```

## 预处理契约

`current_origin.jpg`(1920×1080) → 灰度 → 三通道同值（gray3）→ **不缩放**保存为 PNG。
bbox 坐标完全不变。letterbox 640×640 / padding 114 / `/255` 一次性归一化全部交给
Ultralytics 内部处理，所以保存的 PNG 必须是正常 uint8，**不能预先 /255**。

quick-test 每个视频同样走 灰度 → 三通道 → imgsz 640，阈值在看结果之前就固定为
`conf=0.20`、`iou=0.50`。

## 两个容易踩的坑

1. `dataset.yaml` 的 `path:` **必须写绝对路径**。Ultralytics 会把相对 `path` 拼到它自己的
   全局 `datasets_dir`（默认在用户目录），第一次训练就是因为这个报
   `images not found`。
2. 五个 quick-test 视频来自 `BNDSTT_MVP_v1/split_manifest.csv` 中 `split == quick_test`
   的固定条目，session 与 train/val 完全不重叠；不要因为效果不好而重新挑视频。
