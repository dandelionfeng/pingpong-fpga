> ## ⚠️ DEPRECATED / INVALIDATED EXPERIMENT
>
> **本 PR 描述基于已作废的 29-image run，不得再作为最终 PR 正文使用。**
>
> 该 run 的 GT 为 ChatGPT 自动标注，后经复核发现存在**语义错误**；
> "29/29 PASS" 仅证明流程自洽，不证明标注正确。
> 类别 `0 ball / 1 hand / 2 racket` 中的 **hand 路线已永久取消**。
>
> **请改用** `reports/C_FINAL_HANDOFF_V1.md` 作为 C 端收口说明。
> 状态：`INVALID FOR FINAL EVALUATION`。原文保留不删。

# C: add BNDSTT YOLOv8n ball/hand/racket MVP pipeline

## Summary

- BNDSTT serve-scene detection MVP, 3 classes: `0 ball`, `1 hand`, `2 racket`
- gray3 preprocessing (grayscale replicated to R=G=B), native 1920×1080, Ultralytics letterbox 640
- one fixed YOLOv8n GPU training run (25 epochs, seed 42, deterministic)
- held-out qualitative quick-test over the five frozen `quick_test` videos
- **PROTOTYPE / MVP — not a competition-final model**

## Dataset

Single permitted GT source: `CHATGPT_BNDSTT_MVP_GT_V1.zip`
SHA256 `ff24236cb69e700640cc9b342ed83e939edebe4c25b72d8c2e1226f4316882eb` (verified match).

29 curated frames, read strictly from `curated_manifest.csv`; the old DeepSeek 80-packet
outputs are never globbed, so no legacy label, proposal or auto box can enter the dataset.

| split | images | ball | hand | racket |
| --- | --- | --- | --- | --- |
| train | 23 | 21 | 31 | 7 |
| val | 6 | 6 | 10 | 4 |
| total | 29 | 27 | 41 | 11 |

All 29 GT files were rendered back onto `current_origin.jpg` and inspected individually:
**29/29 PASS**, no systematic coordinate offset. Split integrity preserved (no re-shuffle,
train/val sessions disjoint).

Environment: torch 2.5.1+cu121, CUDA 12.1, RTX 4060 Laptop 8 GB, ultralytics 8.2.82,
Python 3.12.14. No pip install was run, so the CUDA PyTorch build was never at risk.

## Validation

val = 6 images / 20 instances. **Metrics are preliminary and statistically unstable due to
the very small MVP validation set.** This is not a competition accuracy claim.

| class | P | R | mAP50 | mAP50-95 | val instances |
| --- | --- | --- | --- | --- | --- |
| **all** | 0.0016 | 0.100 | 0.0011 | 0.0005 | 20 |
| ball | 0.0000 | 0.000 | 0.0000 | 0.0000 | 6 |
| hand | 0.0047 | 0.300 | 0.0032 | 0.0015 | 10 |
| racket | 0.0000 | 0.000 | 0.0000 | 0.0000 | 4 |

**Model quality gate: NOT PASSED.** mAP50 was ≈ 0 in every one of the 25 epochs; inference
on the model's own training images finds no box above conf 0.05 with best IoU 0.00; the
highest confidence anywhere on the held-out videos was 0.014.

Verified this is not a pipeline bug: labels converted back to pixels match the source JSON
with 0 mismatches across 29 files, image/label pairing is complete, the gray3 contract holds
(R=G=B, 1920×1080) for all 29 images, and the training mosaic shows correct boxes and class
ids. The remaining cause is data quantity — 23 training images and 11 racket instances.

## Testing

- `python tools/check_repo.py --staged` → **PASS** (0 problems)
- `python -m unittest discover -s tests -v` → **PASS**, 10 tests OK
- `git diff --cached --check` → clean
- 5 held-out videos executed end to end (5/5), producing annotated MP4 + per-frame JSONL

## Quick-test (qualitative only)

The five `quick_test` videos come from the frozen `split_manifest.csv`; their SHA256 values
re-verified (5/5) and their sessions are disjoint from every train/val session. Thresholds
were fixed before looking at results: `conf = 0.20`, `iou = 0.50`.

| video | frames | detections | ms/frame |
| --- | --- | --- | --- |
| quick_01 | 42 | 0 | 27.1 |
| quick_02 | 44 | 0 | 25.9 |
| quick_03 | 44 | 0 | 24.3 |
| quick_04 | 47 | 0 | 24.7 |
| quick_05 | 36 | 0 | 24.9 |

At the fixed threshold **no ball, hand or racket detection appears in any of the 5 videos**.
There is no GT for these videos, so no precision/recall/mAP is claimed — only this
qualitative statement. Inference is ≈25 ms/frame on the RTX 4060.

## Why this PR is a DRAFT

`model quality gate not passed`: all three classes have mAP50 ≈ 0 and the held-out videos
produce no detection. The engineering path is proven and worth landing; the trained weights
are not usable. One clean MVP run was performed and was not retried, re-tuned or
threshold-tweaked.

## Limitations

- 29 images only; validation is 6 images / 20 instances; racket has only 4 val instances
- domain gap: BNDSTT colour footage reduced to gray3 vs the target OV9281 grayscale camera
- no OV9281 fine-tuning, no ONNX, no RKNN/INT8, no RK3576 board validation, no C++ DFL/NMS
- needs much more GT, many more racket samples and hard ball cases before a formal version

## Not committed on purpose

Data derivatives and large artifacts stay local and Git-ignored: the GT package, the 29
images, the gray3 dataset, `best.pt` / `last.pt`, `yolov8n.pt`, run outputs, annotated MP4s
and preview images. Git keeps the code, the README and the SHA256 provenance records.

## Reproduce

```powershell
$python = ".\.venv\c-detector\Scripts\python.exe"
& $python vision\bndstt_mvp\curated_gt.py validate
& $python vision\bndstt_mvp\curated_gt.py qa --out-dir artifacts\runs\bndstt_yolov8n_mvp_v1\qa
& $python vision\bndstt_mvp\curated_gt.py build --out artifacts\files\datasets\BNDSTT_YOLO_MVP_V1
& $python vision\bndstt_mvp\curated_gt.py roundtrip --dataset artifacts\files\datasets\BNDSTT_YOLO_MVP_V1 --out-dir artifacts\runs\bndstt_yolov8n_mvp_v1\roundtrip
& $python vision\bndstt_mvp\train_mvp.py
& $python vision\bndstt_mvp\validate_mvp.py --weights artifacts\runs\bndstt_yolov8n_mvp_v1\weights\best.pt --out artifacts\runs\bndstt_yolov8n_mvp_v1\validation
& $python vision\bndstt_mvp\quick_test_mvp.py --weights artifacts\runs\bndstt_yolov8n_mvp_v1\weights\best.pt --out artifacts\quick_test\bndstt_yolov8n_mvp_v1
```

Full write-up: `reports/C_DETECTOR_MVP_V1.md`
