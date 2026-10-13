> ## ⚠️ DEPRECATED / INVALIDATED EXPERIMENT
>
> **本文档描述的 29-image run 已被判定为不可靠，不得用于任何正式结论。**
>
> 原因（2026-10-13 复核确认）：
>
> 1. 该 run 使用的 GT 来自 **ChatGPT 自动生成标注**，后来发现存在**语义错误**
>    （hand / racket 的类别语义与人工复核结果不一致）；
> 2. 因此 "**29/29 PASS**" 只证明了**流程自洽**（坐标未偏移、R=G=B、图标签配对完整），
>    **不能**证明标注本身正确，更**不能**作为模型质量证据；
> 3. 类别体系 `0 ball / 1 hand / 2 racket` 中的 **hand 路线已被永久取消**
>    （见 `vision/c_perception_v2/FINAL_ARCHITECTURE.md`）。
>
> **替代方案**：C 端感知已完全迁移到公开数据路线
> （`tabletennis_ball_racket_v1`，1480 张，类别 `0 ball / 1 racket`）
> + 官方 RacketVision BallTrack + `yolov8n-pose` 手腕关键点。
> 正式指标见 `reports/C_FINAL_HANDOFF_V1.md`。
>
> **状态**：`INVALID FOR FINAL EVALUATION`。原文一字未改，仅保留作历史记录。

# C-side detector MVP v1 — BNDSTT YOLOv8n ball / hand / racket

**Scope: PROTOTYPE / MVP. This is NOT a competition-final model.**
No ONNX, no RKNN, no RK3576 board validation, no OV9281 fine-tuning was performed.

The purpose of this run was to prove the C-side engineering path end to end:
curated GT → schema/count gate → gray3 dataset → JSON→YOLO conversion → GPU training →
validation → held-out video inference → repository checks → PR.

**The engineering path is proven. The model itself did not learn, and that is reported as-is.**

---

## A. Scope

| item | value |
| --- | --- |
| task | object detection, 3 classes |
| classes | `0 ball`, `1 hand`, `2 racket` |
| model | YOLOv8n (COCO-pretrained `yolov8n.pt`) |
| input contract | grayscale replicated to R=G=B ("gray3"), native 1920×1080 |
| letterbox | Ultralytics internal, 640×640, padding 114 |
| normalisation | `/255` once, inside Ultralytics (never pre-applied to the PNGs) |

## B. Dataset

Source: `CHATGPT_BNDSTT_MVP_GT_V1.zip`, the single permitted GT input for MVP v1.

- ZIP SHA256 `ff24236cb69e700640cc9b342ed83e939edebe4c25b72d8c2e1226f4316882eb`
  (matches the expected hash exactly; size 2 054 542 bytes)
- extracted to `artifacts/files/datasets/BNDSTT_MVP_v1/chatgpt_curated_gt_v1/`
- **29 curated frames**: 23 train / 6 val
- the previous DeepSeek 80-packet outputs were **not** used as labels; the curated
  manifest is read explicitly and no directory is globbed, so nothing from
  `deepseek_annotation/outputs/` can enter this dataset

| split | images | ball | hand | racket |
| --- | --- | --- | --- | --- |
| train | 23 | 21 | 31 | 7 |
| val | 6 | 6 | 10 | 4 |
| **total** | **29** | **27** | **41** | **11** |

These counts match the mandated gate exactly. Splits are frozen from
`curated_manifest.csv`; no re-shuffling, and train/val sessions remain disjoint.

GT QA: all 29 JSON files were rendered back onto the original `current_origin.jpg` and
inspected one by one. Every ball / hand / racket box sits on the intended object, and
there is no systematic coordinate offset. **QA verdict: 29/29 PASS.**

## C. Preprocessing contract

`current_origin.jpg` (1920×1080) → grayscale → identical value in R, G and B → saved as a
lossless PNG at native size. Verified on all 29 images: `R == G == B` and `1920×1080`,
no resize and no letterbox baked into the files, bbox coordinates unchanged. Ultralytics
performs the letterbox and the single `/255`.

## D. Environment

| item | value |
| --- | --- |
| interpreter | `.venv\c-detector\Scripts\python.exe` |
| Python | 3.12.14 |
| torch | 2.5.1+cu121 |
| torchvision | 0.20.1+cu121 |
| CUDA (torch) | 12.1, `torch.cuda.is_available() == True` |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, 8.0 GB |
| ultralytics | 8.2.82 |

Ultralytics and its dependencies were already present in the CUDA venv; **no pip install
was run**, so the CUDA PyTorch build was never at risk of being replaced.

## E. Training

Single formal run, no hyper-parameter search, no second seed.

| parameter | value |
| --- | --- |
| model | `yolov8n.pt` (COCO pretrained) |
| epochs | 25 (completed) |
| imgsz | 640 |
| batch | 8 |
| device | 0 |
| workers | 4 |
| amp | True |
| seed | 42 |
| deterministic | True |
| patience | 25 |

- run directory: `artifacts/runs/bndstt_yolov8n_mvp_v1/` (ignored by Git)
- weights: `weights/best.pt`, `weights/last.pt` — both present
- `results.csv` present, 25 epochs recorded, **no NaN loss**
- `best.pt` SHA256: `d863914f8434ec34d78b9774333a5348d2813343ebc601dbc2298d6618e4478d`
- training loss decreased normally (`box_loss` 4.57 → 2.50, `cls_loss` 10.6 → 5.4), and the
  `train_batch0.jpg` mosaic confirms images and labels are correctly paired

## F. Metrics

Validation set: 6 images, 20 instances. **Preliminary and statistically unstable because of
the very small MVP validation set.** Not a competition accuracy figure.

| class | P | R | mAP50 | mAP50-95 | val instances |
| --- | --- | --- | --- | --- | --- |
| **all** | 0.0016 | 0.100 | 0.0011 | 0.0005 | 20 |
| ball | 0.0000 | 0.000 | 0.0000 | 0.0000 | 6 |
| hand | 0.0047 | 0.300 | 0.0032 | 0.0015 | 10 |
| racket | 0.0000 | 0.000 | 0.0000 | 0.0000 | 4 |

### Model quality verdict: **FAILED**

This is not a marginal result that a nicer threshold could rescue:

- validation mAP50 was ≈ 0 for **every one of the 25 epochs**, including the best epoch;
- inference on the model's **own training images** finds no box above conf 0.05 and the
  best IoU against ground truth is 0.00 — the model did not even fit the training set;
- on the 5 held-out videos the highest confidence produced anywhere, at conf 0.0001, was
  **0.014**, i.e. an order of magnitude below the fixed 0.20 threshold.

Possible causes were checked rather than assumed:

- label conversion: all 29 label files were converted back to pixels and compared with the
  source JSON — **0 mismatches**;
- image/label pairing: 23/23 train and 6/6 val, perfectly paired;
- gray3 contract: 0 violations over all 29 images;
- training mosaic: boxes drawn on the correct objects with the correct class ids.

The remaining explanation is data quantity: 23 training images with 59 boxes and 11 racket
instances is far below what YOLOv8n needs to move its COCO prior onto three new classes.
**One clean MVP run was performed and was not retried or tuned**, per the task rules.

## G. Held-out quick-test

The 5 videos are the frozen quick-test entries in
`artifacts/files/datasets/BNDSTT_MVP_v1/split_manifest.csv` (`split == quick_test`). Their
SHA256 values were re-verified against the manifest (5/5 match) and their sessions are
disjoint from every train and val session — they were never trained on, validated on, tuned
on, or annotated. They were **not** re-chosen based on results.

Preprocessing: frame → grayscale → 3 identical channels → `imgsz 640`.
Thresholds **fixed before looking at any result**: `conf = 0.20`, `iou = 0.50`.

| ordinal | session | frames | detections | ms/frame |
| --- | --- | --- | --- | --- |
| quick_01 | 20240525_141249_Output_Group1 | 42 | 0 | 27.1 |
| quick_02 | 20240428_145527_Output_Group1 | 44 | 0 | 25.9 |
| quick_03 | 20240524_184455_Output_Group1 | 44 | 0 | 24.3 |
| quick_04 | 20240503_162502_Output_Group1 | 47 | 0 | 24.7 |
| quick_05 | 20240503_163315_Output_Group1 | 36 | 0 | 24.9 |

Qualitative conclusion: **no ball, hand or racket detection appears in any of the 5 videos**
at the fixed threshold. Every frame's `result.plot()` is therefore the untouched grayscale
frame. There is no GT for these videos, so no precision / recall / mAP is reported — only
this qualitative statement. Inference speed is ~25 ms/frame on the RTX 4060 for a 640×640
letterboxed input.

Outputs (all Git-ignored): `artifacts/quick_test/bndstt_yolov8n_mvp_v1/` with one annotated
MP4, one per-frame JSONL (`frame_idx`, `timestamp_ms`, `detections[class, class_id,
confidence, bbox_xyxy]` in original video pixels), a mid-video preview, and `summary.json`.

## H. Limitations

- **29 images only**; this cannot support a trainable detector.
- Validation is 6 images / 20 instances; racket has only **4** validation instances.
  Every metric here is preliminary and statistically unstable.
- The model quality gate **did not pass** (all classes mAP50 ≈ 0; zero quick-test detections).
- Domain gap: GT comes from BNDSTT 1920×1080 colour footage reduced to gray3, while the
  target sensor is an OV9281 grayscale USB camera. No domain fine-tuning was done.
- Not validated on RK3576 hardware, not converted to ONNX or RKNN, no INT8 calibration.
- Still missing for a formal version: more BNDSTT GT, many more racket samples, hard
  ball examples (blur, occlusion, high toss), real OV9281 data, and a C++ DFL/NMS path.

## I. Artifact provenance

| artifact | SHA256 |
| --- | --- |
| `CHATGPT_BNDSTT_MVP_GT_V1.zip` | `ff24236cb69e700640cc9b342ed83e939edebe4c25b72d8c2e1226f4316882eb` |
| `artifacts/runs/bndstt_yolov8n_mvp_v1/weights/best.pt` | `d863914f8434ec34d78b9774333a5348d2813343ebc601dbc2298d6618e4478d` |

Large files stay local and Git-ignored: the GT package, the 29 images, the gray3 dataset,
`best.pt` / `last.pt`, `yolov8n.pt`, run outputs, annotated MP4s and preview images.

## J. Reproducing

```powershell
# 0. CUDA venv only
.\.venv\c-detector\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"

# 1. GT gate (must print VALIDATE PASS)
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\curated_gt.py validate

# 2. visual QA of every curated bbox
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\curated_gt.py qa --out-dir artifacts\runs\bndstt_yolov8n_mvp_v1\qa

# 3. gray3 dataset (counts gate printed)
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\curated_gt.py build --out artifacts\files\datasets\BNDSTT_YOLO_MVP_V1

# 4. label round-trip (must print ROUND TRIP PASS)
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\curated_gt.py roundtrip --dataset artifacts\files\datasets\BNDSTT_YOLO_MVP_V1 --out-dir artifacts\runs\bndstt_yolov8n_mvp_v1\roundtrip

# 5. the single formal training run
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\train_mvp.py

# 6. validation metrics + prediction previews
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\validate_mvp.py --weights artifacts\runs\bndstt_yolov8n_mvp_v1\weights\best.pt --out artifacts\runs\bndstt_yolov8n_mvp_v1\validation

# 7. held-out quick-test (5 frozen videos, conf 0.20 / iou 0.50)
.\.venv\c-detector\Scripts\python.exe vision\bndstt_mvp\quick_test_mvp.py --weights artifacts\runs\bndstt_yolov8n_mvp_v1\weights\best.pt --out artifacts\quick_test\bndstt_yolov8n_mvp_v1
```

One environment note worth keeping: `dataset.yaml` must carry an **absolute** `path:`.
Ultralytics resolves a relative `path:` against its own global `datasets_dir`, which is not
inside this repository, and the very first launch failed for exactly that reason.
