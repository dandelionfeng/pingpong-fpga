# DeepSeek BNDSTT MVP labeling report — fixed 80-packet visual GT pass

Scope: the **fixed 80-packet MVP set** (train 64 / val 16). The remaining 70 packets stay `pending` for MVP v2.

## 1. Method — visual review only

Every one of the 80 packets was reviewed by looking at its images:

- `current_origin.jpg` — the only image annotated, and the only bbox coordinate space,
- `prev_origin.jpg` / `next_origin.jpg` — to confirm a small or blurred ball's motion and to avoid
  calling a static wall mark a ball,
- `current_crop_reference.jpg` — visual aid; its coordinates were never measured from,
- magnified crops and a labelled pixel grid — used to place a box on the object.

Reading aids were **display only** (magnified crops, grids, three-frame strips, candidate insets).
No formal bbox came from pose keypoints, skin thresholds, wrist proximity, distance filters,
directional clipping, template matching, candidate scores or the old proposal files.

### Provenance

Every formal box is `VISUAL_CONFIRMED`. The record file carries `review_state: "visual_review"`,
and `tools/deepseek_labeling/_work/visual_review.json` holds exactly the boxes that were decided by
looking at the images. A separate audit file lists every box that was withdrawn.

**Withdrawn in this pass: 104 `AUTO_HAND_PROPOSAL` boxes.** They had been added by
pose + skin + distance filtering and were removed from `objects` — the JSON files were kept, only
the automated hand objects were dropped. They are still visible as debug aids in
`add_hands.py` / `pose_landmarks.py` output, but they are not Ground Truth.

The 4 racket boxes that existed before were re-checked visually; 6 more rackets were found and
confirmed in this pass, for 10 formal racket boxes. No racket box was accepted from a proposal.

## 2. Coverage

| item | count |
| --- | --- |
| packets processed | 80 |
| train GT | 64 |
| val GT | 16 |
| `deepseek_reviewed` | 60 |
| `needs_manual_review` | 20 |
| left `pending` | 70 |

Split integrity: no packet's `split` was changed; the subset takes whole sessions, and the train
and val session sets are disjoint (train 21 sessions, val 4 sessions, **zero overlap**).
`source_id`, `session_id`, `frame_id` and `packet_id` are untouched; no frames were re-extracted
and no data was added.

## 3. Instance counts

| class | all | train | val |
| --- | --- | --- | --- |
| 0 ball | 64 | 50 | 14 |
| 1 hand | 70 | 58 | 12 |
| 2 racket | 10 | 10 | 0 |
| **total** | **144** | 118 | 26 |

Confidence: `high` 4, `medium` 136, `low` 4.

- packets with `uncertain_objects: ["ball"]` and therefore no ball box: **16**
- packets with two labelled hands: 13
- packets with a labelled racket: 9

## 4. Validation

`vision/bndstt_mvp/import_deepseek_labels.py`, run against a temporary labels directory so the
official split was untouched:

```
{ "accepted_gt": 60, "needs_manual_review": 20, "rejected": 0, "missing": 70 }
```

Independent checks over the 80 official JSON files: 0 problems.

- 80/80 parse; `packet_id` matches the file name; every file is inside the fixed subset;
- `image_width` / `image_height` match the packet metadata (1920x1080);
- `class_id` is always 0/1/2 and matches `class_name`;
- every bbox satisfies `0 <= x1 < x2 <= 1920` and `0 <= y1 < y2 <= 1080`;
- no duplicate bbox, no zero-size box, no out-of-bounds box, no rejected file;
- no `AUTO_HAND_PROPOSAL` box remains in `objects`.

## 5. Honest limitations

1. **Ball remains the hard class.** 64 packets carry a ball box; 16 do not and are marked
   `uncertain_objects: ["ball"]`. Of the 64, most are `medium`: the ball is typically 6-20 px and
   often motion-blurred, so the box follows the visible blurred extent.
2. **A white printed logo on the players' dark jerseys is a systematic ball-like distractor**
   (bright, round, ball-sized, early hold frames). Those packets were left uncertain rather than
   accepting the logo as a ball.
3. **Several balls are small and blurred enough that a second opinion is worthwhile.** The weakest
   cases are recorded as `low` confidence (4 objects) and are routed to manual review.
4. **Hand boxes bound the visible hand**, not the whole forearm; they can clip fingertips. In frames
   where the hand was not reliably visible, no hand box was written rather than guessing.
5. **Racket coverage stays low by design.** In most service frames the paddle is edge-on, blurred,
   or occluded; 9 packets have a racket box, one of which is `low` confidence.
6. **20 packets are `needs_manual_review`** and must not be treated as training labels until a
   human confirms them.

## 6. Packet defect found

All 150 `current_crop_reference.jpg` files are **PNG data with a `.jpg` extension**. A loader that
trusts the suffix will fail or mis-decode. The origin frames are valid JPEG. This is a packaging
defect, not an annotation defect.

## 7. Outputs

| what | path |
| --- | --- |
| formal GT JSON (80) | `artifacts/files/datasets/BNDSTT_MVP_v1/deepseek_annotation/outputs/<packet_id>.json` |
| manifest with statuses | `artifacts/files/datasets/BNDSTT_MVP_v1/deepseek_annotation/manifests/mvp_v1_packets.csv` |
| final acceptance contact sheet (20) | `reports/DEEPSEEK_MVP80_FINAL_GT_PREVIEW_20.jpg` |
| visually decided boxes | `tools/deepseek_labeling/_work/visual_review.json` |
| withdrawn-box provenance audit | `tools/deepseek_labeling/_work/provenance_audit.json` |
| reviewed records with evidence text | `tools/deepseek_labeling/_work/decisions_reviewed.json` |
| per-packet QC renders | `tools/deepseek_labeling/_work/gtreview/` |

`accepted_gt` was deliberately **not** written to the manifest; that gate belongs to the later
Codex QA / human acceptance step.

## 8. Next step (not done here)

Handing back for Codex: GT import → YOLOv8n training → quick_test → git check → commit → push →
GitHub PR. The 20-image contact sheet above is the intended human acceptance view before that.
