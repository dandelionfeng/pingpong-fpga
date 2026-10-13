# DeepSeek Vision handoff: BNDSTT ball / hand / racket MVP

## Objective and boundary

This is a **PROTOTYPE / MVP** annotation handoff for a YOLOv8n detector with exactly three classes:

- `0 ball`
- `1 hand`
- `2 racket`

The source is real table-tennis service video from official BNDSTT data. DeepSeek Vision only supplies image bounding boxes. It does not determine release, apex, contact, 16 cm height, service legality, 3D trajectory, stereo geometry, RKNN, or FPGA behavior.

The package contains 150 packets: 120 train and 30 val. It preserves the existing source/session split; quick_test contributes zero packets. Do not move a packet between splits.

## Package

Root: `artifacts/files/datasets/BNDSTT_MVP_v1/deepseek_annotation/`

- Instructions: `README.md`
- Work list: `manifests/mvp_v1_packets.csv`
- Machine-readable schema: `manifests/deepseek_output.schema.json`
- Schema explanation: `OUTPUT_SCHEMA.md`
- Input packets: `packets/<packet_id>/`
- Official DeepSeek JSON destination: `outputs/<packet_id>.json`

Each packet contains:

- `current_origin.jpg`: the only formal annotation image and bbox coordinate space.
- `prev_origin.jpg`, `next_origin.jpg`: temporal context only, normally about 50 ms away.
- `current_crop_reference.jpg`: enlarged visual reference only; never use its coordinates as output.
- `proposal_reference.json`: optional suggestion only.
- `metadata.json`: packet identity, dimensions, paths, timestamps, split, source/session, and labels supplied by BNDSTT.

The bbox coordinates also apply to the packet's `derived_gray3_path` because the gray3 derivative preserves origin geometry. The formal DeepSeek view remains `current_origin.jpg`.

## Critical proposal warning

**Do not mechanically accept proposal boxes.** Visual inspection has already confirmed systematic proposal problems:

- visible balls can have no ball proposal;
- racket proposals can land on the table or net;
- hand proposals can be inaccurate.

Always inspect the images first. A proposal box is not Ground Truth. A missing ball proposal does not mean no ball exists.

## Annotation procedure

1. Read the packet metadata and open current, previous, next, and crop-reference images.
2. Determine objects from visual evidence, using temporal context to distinguish a tiny moving ball from static marks.
3. Draw tight pixel-XYXY boxes in `current_origin.jpg` coordinates only.
4. Follow the class rules in the package `README.md`.
5. If a suspected ball cannot be localized reliably, do not guess; put `"ball"` in `uncertain_objects`.
6. Write one JSON file to `outputs/<packet_id>.json` using the documented schema. Do not create or edit YOLO `.txt` files.

Only valid `status: "reviewed"` JSON may be imported. Low-confidence objects, uncertainty, empty results, invalid or duplicate boxes, extreme boxes, packet mismatches, and dimension mismatches are stopped for review or rejection.

## Provenance and isolation

Existing automatic proposals are isolated under `proposals/` and per-packet `proposal_reference.json`. They are suggestions only. The one earlier Codex-assisted review was reclassified as `legacy_review_candidate`, preserved under `legacy_review_candidate_labels/`, and is ineligible for training. Official DeepSeek `outputs/` is empty at handoff. No proposal was promoted to accepted GT.

Codex conversion and QA tools:

- `vision/bndstt_mvp/import_deepseek_labels.py`
- `vision/bndstt_mvp/render_deepseek_gt.py`

The importer emits YOLO labels only after validation and keeps `needs_manual_review` separate from `accepted_gt`.

## Pipeline smoke test

Five packets were exercised with clearly synthetic fixture JSON under `deepseek_annotation/smoke_test/`; fixture boxes are not real annotations and never enter official outputs. Result:

- 4 valid fixtures converted to normalized YOLO text;
- 1 fixture with uncertain ball routed to `needs_manual_review`;
- 5 rendered QA previews produced;
- official `outputs/` and official GT were untouched.

See `smoke_test/smoke_test_result.json`.

## Training environment (record only; do not train now)

- Python: `.venv/c-detector/Scripts/python.exe`
- PyTorch: `2.5.1+cu121`
- CUDA reported by PyTorch: `12.1`
- `torch.cuda.is_available()`: `True`
- GPU: `NVIDIA GeForce RTX 4060 Laptop GPU`
- VRAM: approximately 8 GB
- Ultralytics actual current state: `8.2.82` is already importable in this CUDA venv from earlier environment repair; no package installation was performed during this handoff.

Training remains prohibited until the labels are complete and the user approves the rendered Ground Truth review.
