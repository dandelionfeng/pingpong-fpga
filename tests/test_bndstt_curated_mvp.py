import math
import unittest

from vision.bndstt_mvp.curated_gt import validate_object, yolo_line


class CuratedMvpConversionTests(unittest.TestCase):
    def test_xyxy_to_normalized_yolo_round_trip(self):
        bbox = (510.0, 215.0, 542.0, 249.0)
        values = yolo_line(0, bbox).split()
        self.assertEqual(values[0], "0")
        xc, yc, width, height = map(float, values[1:])
        restored = (
            (xc - width / 2) * 1920,
            (yc - height / 2) * 1080,
            (xc + width / 2) * 1920,
            (yc + height / 2) * 1080,
        )
        for actual, expected in zip(restored, bbox):
            self.assertTrue(math.isclose(actual, expected, abs_tol=1e-4))

    def test_schema_rejects_class_name_mismatch(self):
        with self.assertRaisesRegex(RuntimeError, "class id/name mismatch"):
            validate_object({"class_id": 0, "class_name": "hand", "bbox_xyxy": [1, 2, 3, 4]}, "P", 0)

    def test_schema_rejects_out_of_bounds_box(self):
        with self.assertRaisesRegex(RuntimeError, "outside"):
            validate_object({"class_id": 2, "class_name": "racket", "bbox_xyxy": [-1, 2, 3, 4]}, "P", 0)

    def test_schema_rejects_bad_class_id(self):
        with self.assertRaisesRegex(RuntimeError, "not 0/1/2"):
            validate_object({"class_id": 7, "class_name": "ball", "bbox_xyxy": [1, 2, 3, 4]}, "P", 0)

    def test_schema_rejects_zero_size_box(self):
        with self.assertRaisesRegex(RuntimeError, "x1<x2"):
            validate_object({"class_id": 0, "class_name": "ball", "bbox_xyxy": [5, 5, 5, 9]}, "P", 0)


if __name__ == "__main__":
    unittest.main()
