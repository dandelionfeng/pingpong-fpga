import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C_ACTUAL = ROOT / "source/native/base/software/pc_pipeline/modules/c_actual"
RKNN = ROOT / "source/native/rk_runtime/c_rknn"


class ThresholdConfigChainTest(unittest.TestCase):
    def test_json_base_conf_is_present(self):
        config = json.loads((ROOT / "app/rk/model-config-int8.json").read_text("utf-8"))
        self.assertEqual(config["diagnostic_thresholds"]["base_conf"], 0.005)
        self.assertEqual(config["diagnostic_thresholds"]["hand"], 0.1)
        self.assertEqual(config["diagnostic_thresholds"]["racket"], 0.1)

    def test_bridge_reads_base_conf_and_reports_actual_values(self):
        text = (C_ACTUAL / "src/detector_backend_c_actual.cpp").read_text("utf-8")
        self.assertIn('config.base_conf=d.value("base_conf"', text)
        self.assertIn('r.diagnostics["base_conf"]', text)
        self.assertIn('r.diagnostics["final_thresholds"]', text)
        self.assertIn('{"config_sha256", configHash_}', text)
        self.assertIn('{"model_sha256", modelHashes_}', text)

    def test_yolo_passes_threshold_to_session(self):
        text = (C_ACTUAL / "src/yolo_detector_onnx.cpp").read_text("utf-8")
        self.assertIn("&run_error, conf_threshold", text)

    def test_rknn_uses_dynamic_threshold_and_keeps_full_dfl(self):
        text = (RKNN / "runtime_session.cpp").read_text("utf-8")
        self.assertIn("candidate_threshold(base_conf", text)
        self.assertIn("candidate_should_skip(maximum_logit", text)
        self.assertIn("C_RKNN_FULL_DFL", text)
        self.assertNotIn("maximum_logit < -3.9f", text)
        self.assertNotIn("confidence<.02f", text)

    def test_generated_bridge_marks_rknn_backend(self):
        # This is checked after a real prepare run in TEST_RESULTS; here we check
        # the source replacement rule exists so generated output cannot regress.
        text = (ROOT / "source/native/tools/board_runtime/prepare_c_rknn.py").read_text("utf-8")
        self.assertIn('r.diagnostics["inference_backend"] = "rknn-runtime"', text)


if __name__ == "__main__":
    unittest.main()
