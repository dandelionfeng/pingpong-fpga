"""Manual annotation tool tests: schema, YOLO conversion and atomic saves.

These use synthetic fixtures only. They never write to the real
BNDSTT_MANUAL_GT_V1 tree and never create a box on a real image.

  python -m unittest tests.test_manual_gt_tools -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vision.bndstt_mvp import manual_annotation_server as server


def synthetic_row(width: int = 1920, height: int = 1080) -> dict:
    return {
        "image_id": "FIXTURE_0001",
        "original_image_path": "images_color/train/FIXTURE_0001.jpg",
        "derived_gray3_path": "images_gray3/train/FIXTURE_0001.png",
        "yolo_label_path": "labels/train/FIXTURE_0001.txt",
        "split": "train",
        "session_id": "FIXTURE_SESSION",
        "source_id": "FIXTURE_SESSION::origin_00001__crop_00001",
        "frame_index": 3,
        "width": width,
        "height": height,
    }


class RecordSchemaTests(unittest.TestCase):
    def test_valid_objects_build_a_human_manual_record(self):
        row = synthetic_row()
        record = server.build_record(
            row,
            [
                {"class_id": 0, "bbox_xyxy": [100, 200, 120, 220]},
                {"class_id": 1, "bbox_xyxy": [500.5, 300.25, 560, 360]},
                {"class_id": 2, "bbox_xyxy": [1000, 600, 1100, 700]},
            ],
            "MANUAL_REVIEWED",
        )
        self.assertEqual(record["annotation_source"], "HUMAN_MANUAL")
        self.assertEqual(record["review_state"], "MANUAL_REVIEWED")
        self.assertEqual(record["image_width"], 1920)
        self.assertEqual(record["image_height"], 1080)
        self.assertEqual([o["class_name"] for o in record["objects"]], ["ball", "hand", "racket"])

    def test_empty_objects_is_allowed_when_reviewed(self):
        record = server.build_record(synthetic_row(), [], "MANUAL_REVIEWED")
        self.assertEqual(record["objects"], [])
        self.assertEqual(server.yolo_lines(record), [])

    def test_bad_class_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "class_id"):
            server.build_record(synthetic_row(), [{"class_id": 5, "bbox_xyxy": [1, 2, 3, 4]}], "MANUAL_REVIEWED")

    def test_out_of_bounds_box_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            server.build_record(synthetic_row(), [{"class_id": 0, "bbox_xyxy": [-5, 10, 30, 40]}], "MANUAL_REVIEWED")

    def test_zero_area_box_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            server.build_record(synthetic_row(), [{"class_id": 0, "bbox_xyxy": [50, 50, 50, 90]}], "MANUAL_REVIEWED")

    def test_box_larger_than_the_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            server.build_record(synthetic_row(), [{"class_id": 2, "bbox_xyxy": [0, 0, 5000, 5000]}], "MANUAL_REVIEWED")

    def test_unsaved_state_is_rejected(self):
        with self.assertRaises(ValueError):
            server.build_record(synthetic_row(), [], "UNLABELED")


class YoloConversionTests(unittest.TestCase):
    def test_normalized_values_are_correct(self):
        record = server.build_record(synthetic_row(), [{"class_id": 0, "bbox_xyxy": [960, 540, 1152, 648]}], "MANUAL_REVIEWED")
        line = server.yolo_lines(record)[0]
        cid, xc, yc, w, h = line.split()
        self.assertEqual(cid, "0")
        self.assertAlmostEqual(float(xc), 0.55, places=6)
        self.assertAlmostEqual(float(yc), 0.55, places=6)
        self.assertAlmostEqual(float(w), 0.1, places=6)
        self.assertAlmostEqual(float(h), 0.1, places=6)

    def test_round_trip_stays_within_one_pixel(self):
        boxes = [
            {"class_id": 0, "bbox_xyxy": [1, 1, 12, 13]},
            {"class_id": 1, "bbox_xyxy": [510, 215, 542, 249]},
            {"class_id": 2, "bbox_xyxy": [1900, 1060, 1920, 1080]},
        ]
        record = server.build_record(synthetic_row(), boxes, "MANUAL_REVIEWED")
        self.assertLessEqual(server.round_trip_error(record), 1.0)

    def test_non_square_image_scales_each_axis_independently(self):
        record = server.build_record(
            synthetic_row(2000, 500), [{"class_id": 1, "bbox_xyxy": [0, 0, 2000, 500]}], "MANUAL_REVIEWED"
        )
        cid, xc, yc, w, h = server.yolo_lines(record)[0].split()
        self.assertAlmostEqual(float(xc), 0.5, places=6)
        self.assertAlmostEqual(float(w), 1.0, places=6)
        self.assertAlmostEqual(float(h), 1.0, places=6)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "record.json"
            server.atomic_write_text(target, '{"a": 1}\n')
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"a": 1})
            leftovers = [p.name for p in Path(tmp).iterdir() if p.name != "record.json"]
            self.assertEqual(leftovers, [], "a temporary file was left behind")

    def test_atomic_write_replaces_existing_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "record.json"
            server.atomic_write_text(target, "first")
            server.atomic_write_text(target, "second")
            self.assertEqual(target.read_text(encoding="utf-8"), "second")


class ServerGuardTests(unittest.TestCase):
    def test_auto_proposals_are_disabled(self):
        self.assertTrue(server.AUTO_PROPOSALS_DISABLED)

    def test_only_saved_states_are_accepted(self):
        self.assertEqual(set(server.STATES), {"UNLABELED", "MANUAL_IN_PROGRESS", "MANUAL_REVIEWED", "NEEDS_REVIEW"})

    def test_classes_are_fixed(self):
        self.assertEqual(server.CLASSES, {0: "ball", 1: "hand", 2: "racket"})

    def test_manifest_covers_the_expected_280_images(self):
        self.assertEqual(len(server.FRAMES_ROWS), 280)
        splits = [r["split"] for r in server.FRAMES_ROWS]
        self.assertEqual(splits.count("train"), 224)
        self.assertEqual(splits.count("val"), 56)

    def test_manifest_has_no_session_leak_between_splits(self):
        train = {r["session_id"] for r in server.FRAMES_ROWS if r["split"] == "train"}
        val = {r["session_id"] for r in server.FRAMES_ROWS if r["split"] == "val"}
        self.assertEqual(train & val, set())

    def test_manual_gt_history_is_preserved_not_required_empty(self):
        """BNDSTT_MANUAL_GT_V1 里的人工标注是历史资产：允许存在，禁止被清空。

        本测试不再断言“必须为空”。它只要求：如果存在人工标注，每个 JSON 都是
        可解析的、且属于既有的 3 类方案（ball/hand/racket），并统计数量供交接记录。
        历史标注不得删除、不得修改；本轮 C perception v2 只把它当只读参考。
        """

        if not server.ANNOTATIONS.exists():
            self.skipTest("BNDSTT_MANUAL_GT_V1/annotations_json not present (nothing to preserve)")
        real = sorted(server.ANNOTATIONS.glob("*.json"))
        for path in real:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("objects", payload)
            for obj in payload["objects"]:
                # 旧 3 类方案的历史 id；新的 V2 方案不再训练 hand
                self.assertIn(obj.get("class_id"), (0, 1, 2))

    def test_c_perception_v2_never_reads_manual_gt(self):
        """本轮 V2 训练/评估流程绝对不读取 BNDSTT_MANUAL_GT_V1（尤其不用其 hand 标签）。"""
        repo_root = Path(__file__).resolve().parents[1]
        v2_dir = repo_root / "vision" / "c_perception_v2"
        self.assertTrue(v2_dir.is_dir(), "vision/c_perception_v2 must exist")

        # 唯一允许提到旧手工 GT 的地方：只读的尺寸对比（annotations_json / bndstt_manual_gt_dir）
        allowed_markers = ("bndstt_manual_gt_dir", "annotations_json")
        offenders = []
        for source in sorted(v2_dir.glob("*.py")):
            for line in source.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                is_readonly_declaration = any(
                    marker in stripped for marker in allowed_markers
                ) or "datasets_dir" in stripped
                if "BNDSTT_MANUAL_GT_V1" in stripped and not is_readonly_declaration:
                    offenders.append(source.name + ": " + stripped)
                if "labels_yolo" in stripped or "manual_annotation_manifest" in stripped:
                    offenders.append(source.name + ": " + stripped)
        self.assertEqual(offenders, [], f"V2 must not read manual GT: {offenders}")

        # 训练/评估入口指向公开数据二分类集，绝不指向手工 GT
        import sys as _sys

        if str(repo_root) not in _sys.path:
            _sys.path.insert(0, str(repo_root))
        from vision.c_perception_v2.config import PATHS as _PATHS

        self.assertIn("tabletennis_ball_racket_v1", str(_PATHS.br_data_yaml))
        self.assertNotIn("BNDSTT", str(_PATHS.br_data_yaml))
        self.assertNotIn("BNDSTT_MANUAL_GT", str(_PATHS.br_data_yaml))

        # V2 类别只有 ball/racket，hand 已取消
        from vision.c_perception_v2 import CLASS_NAMES as _CLASS_NAMES

        self.assertEqual(tuple(_CLASS_NAMES), ("ball", "racket"))


if __name__ == "__main__":
    unittest.main()
