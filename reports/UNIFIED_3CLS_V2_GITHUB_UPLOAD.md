# 统一三分类模型 · GitHub 上传记录

日期：2026-10-24　分支：`codex/c-pc-detector`
模型提交：`83fdf2cc8e0cb8f8d143724c1e9ad4c11c6ca38f`

## 1. 上传内容（远程已核验）

| 文件 | 仓库路径 | 大小 | SHA256 |
| --- | --- | --- | --- |
| 三分类 ONNX | `artifacts/handoff/UNIFIED_3CLS_V2_FOR_CAPTAIN/pingpong_yolov8n_gray_3cls_v2_960.onnx` | 12,161,114 B | `ed4653652c1735cfc1dec32354b3591a5f6ebbdc8b1d5c5eadd7dd276e36645f` |
| 训练权重 | `artifacts/runs/unified_3cls_v2/weights/best.pt` | 6,271,011 B | `73f460a8276afbc4a61e56dac21debd50bb6409da643fe3f83079b8c2c3d3347` |
| 队长交付 ZIP | `artifacts/handoff/UNIFIED_3CLS_V2_FOR_CAPTAIN.zip` | 10,827,927 B | `d843164a543f2c48dfd687afb8b3a552ff3cce1cf08a77d40da6c09de4287be8` |
| 仓库说明 | `.../UNIFIED_3CLS_V2_FOR_CAPTAIN/REPO_README.md` | 4,144 B | 见 SHA256SUMS |
| 队长说明 | `.../README_CAPTAIN.md` | 5,418 B | 同上 |
| 模型卡 | `.../MODEL_CARD.md` | 1,872 B | 同上 |
| 输入输出协议 | `.../INPUT_OUTPUT_PROTOCOL.md` | 1,120 B | 同上 |
| 逐类评测 | `.../EVALUATION_REPORT.md` | 3,606 B | 同上 |
| 推理脚本 | `.../infer_unified_3cls.py` | 9,486 B | 同上 |
| 示例图 | `.../sample_hand.jpg`、`sample_racket.jpg` | 54,647 / 273,617 B | 同上 |
| 校验和 | `.../SHA256SUMS.txt` | — | — |

## 2. 推送

| 项 | 值 |
| --- | --- |
| 推送前远程头 | `58bb405a50c554d2762034b15e004e4c8b31f12f` |
| 本次推送范围 | `58bb405..83fdf2c`（fast-forward，5 个本地提交） |
| main | `4ba0939b1da393cfeee103784f91378e2caa7bd6`，**未改动** |
| force push / 合并 PR | **都没有** |

## 3. 远程核验（实际执行）

1. `git ls-remote origin codex/c-pc-detector` → `83fdf2c`，与本地 HEAD 一致；
2. **浅克隆**到 `C:\pp_models\u3cls_remote_verify`，克隆 HEAD = `83fdf2c`；
3. 对克隆出的三个二进制重算 SHA256 → **与本地逐个一致**（见 §1）；
4. **解压远程 ZIP** 到 `C:\pp_models\u3cls_remote_unzip` → 9 个文件，内含 ONNX 哈希
   `ed465365…` 一致；
5. 直接运行**远程解压出来的**推理脚本 → 成功：10 帧，ball 5 / hand 14 / racket 8，48 ms/帧；
6. GitHub contents API（`?ref=83fdf2c`）逐个确认文件存在且大小一致。

## 4. 未提交 / 未推送

- 本地工作区仍有上一轮遗留的未跟踪项（`artifacts/racket_yolo_v2/`、`artifacts/racket_yolo_v3/`、
  `reports/*.jpg` 预览图），**本轮未提交**，也不属于本次交付。
- 本地与远程已同步（`git status -sb` 显示 ahead/behind 均为 0）。

## 5. 仓库体积

GitHub API 报告仓库约 **40,540 KB**（本次新增约 29 MB 二进制）。
仓库既有的 `tools/check_repo.py` 对 >10 MiB 的文件会给 FAIL 提示
（此前 4 个 Ball ONNX 已触发同样提示）；本次 3 个二进制同样会触发，
这是**仓库既有规范与"模型入库"需求之间的冲突**，本轮按任务要求执行，
并在报告中明确记录，未修改检查规则。
