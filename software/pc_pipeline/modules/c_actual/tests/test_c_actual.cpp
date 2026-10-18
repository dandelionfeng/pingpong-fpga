// c_actual tests: geometry, gray3 contract, and optional end-to-end checks.
//
// The geometry/gray3 tests need no model files, so they run anywhere. The
// end-to-end tests are skipped unless C_ACTUAL_MODELS_DIR is set to a directory
// holding balltrack_tracknetv3.onnx, hand_yolov8n_gray.onnx and
// racket_yolov8n.onnx.

#include <c_perception_engine.hpp>

#include <opencv2/imgproc.hpp>

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

int failures = 0;
int checks = 0;

void check(bool condition, const std::string &name) {
  ++checks;
  if (condition) {
    std::cout << "  [PASS] " << name << "\n";
  } else {
    ++failures;
    std::cout << "  [FAIL] " << name << "\n";
  }
}

void expectThrows(const std::function<void()> &fn, const std::string &name) {
  ++checks;
  try {
    fn();
    ++failures;
    std::cout << "  [FAIL] " << name << " (no exception thrown)\n";
  } catch (const std::exception &) {
    std::cout << "  [PASS] " << name << "\n";
  }
}

void testGray3() {
  std::cout << "gray3 contract\n";
  cv::Mat gray(4, 4, CV_8UC1, cv::Scalar(77));
  cv::Mat three = c_actual::preprocess::grayToGray3(gray);
  check(three.type() == CV_8UC3, "gray3 has 3 channels");
  bool identical = true;
  for (int y = 0; y < three.rows; ++y) {
    for (int x = 0; x < three.cols; ++x) {
      const cv::Vec3b px = three.at<cv::Vec3b>(y, x);
      if (px[0] != 77 || px[1] != 77 || px[2] != 77) identical = false;
    }
  }
  check(identical, "all three channels equal the grayscale value");

  cv::Mat colour(4, 4, CV_8UC3, cv::Scalar(1, 2, 3));
  expectThrows([&] { c_actual::preprocess::grayToGray3(colour); },
               "grayToGray3 rejects CV_8UC3 input");

  c_actual::CPerceptionEngine engine;
  cv::Mat gray_frame(8, 8, CV_8UC1, cv::Scalar(10));
  expectThrows(
      [&] {
        c_actual::FrameMeta meta;
        engine.inferGray(colour, meta);
      },
      "inferGray rejects a non-GRAY8 frame");
}

void testLetterbox() {
  std::cout << "letterbox geometry\n";
  // 1920x1080 into 640: scale = 640/1920 = 0.3333, height 360, pad_y = 140.
  cv::Mat wide(1080, 1920, CV_8UC3, cv::Scalar(0, 0, 0));
  float scale = 0.f;
  int pad_x = 0, pad_y = 0;
  cv::Mat out = c_actual::preprocess::letterbox(wide, 640, &scale, &pad_x, &pad_y);
  check(out.cols == 640 && out.rows == 640, "letterbox output is 640x640");
  check(std::fabs(scale - (640.0f / 1920.0f)) < 1e-6f, "scale is 640/1920");
  check(pad_x == 0, "no horizontal padding for a wide frame");
  check(pad_y == 140, "vertical padding is 140");

  // Square frame: no padding at all.
  cv::Mat square(500, 500, CV_8UC3, cv::Scalar(0, 0, 0));
  cv::Mat out2 = c_actual::preprocess::letterbox(square, 640, &scale, &pad_x, &pad_y);
  check(scale == 1.28f && pad_x == 0 && pad_y == 0, "square frame scales with no padding");
}

void testUnletterbox() {
  std::cout << "coordinate mapping back to the original image\n";
  // Detection at the exact centre of a 1920x1080 letterboxed into 640.
  const float scale = 640.0f / 1920.0f;
  const int pad_x = 0, pad_y = 140;
  const float cx = 320.f, cy = 140.f + 180.f;  // centre of the content band
  c_actual::Box box = c_actual::postprocess::unletterbox(cx, cy, 40.f, 40.f, 0.9f, 0, scale,
                                                         pad_x, pad_y, 1920, 1080);
  const float expected_cx = 960.f, expected_cy = 540.f;
  const float got_cx = box.x + box.w * 0.5f, got_cy = box.y + box.h * 0.5f;
  check(std::fabs(got_cx - expected_cx) < 1.5f, "centre x maps back to 960");
  check(std::fabs(got_cy - expected_cy) < 1.5f, "centre y maps back to 540");
  check(box.w > 0.f && box.h > 0.f, "box keeps a positive size");

  // Clamping: a detection far outside the letterbox must clamp into the image.
  c_actual::Box clamped = c_actual::postprocess::unletterbox(-500.f, -500.f, 40.f, 40.f, 0.5f, 0,
                                                             scale, pad_x, pad_y, 1920, 1080);
  check(clamped.x >= 0.f && clamped.y >= 0.f, "out-of-frame box clamps to the image origin");
}

void testNms() {
  std::cout << "NMS\n";
  c_actual::Box a{0.f, 0.f, 100.f, 100.f, 0.9f, 0, "hand"};
  c_actual::Box b{5.f, 5.f, 100.f, 100.f, 0.8f, 0, "hand"};   // heavy overlap
  c_actual::Box c{500.f, 500.f, 100.f, 100.f, 0.7f, 0, "hand"};  // disjoint
  auto kept = c_actual::postprocess::nms({a, b, c}, 0.5f, 100);
  check(kept.size() == 2, "overlapping duplicate suppressed");
  check(kept[0].confidence >= kept[1].confidence, "kept boxes are sorted by confidence");

  auto limited = c_actual::postprocess::nms({a, b, c}, 0.5f, 1);
  check(limited.size() == 1, "max_det is honoured");

  // Different classes never suppress each other.
  c_actual::Box hand{0.f, 0.f, 100.f, 100.f, 0.9f, 0, "hand"};
  c_actual::Box racket{5.f, 5.f, 100.f, 100.f, 0.8f, 1, "racket"};
  auto cross = c_actual::postprocess::nms({hand, racket}, 0.5f, 100);
  check(cross.size() == 2, "class-aware NMS keeps different classes");
}

void testIou() {
  std::cout << "IoU\n";
  c_actual::Box a{0.f, 0.f, 10.f, 10.f, 1.f, 0, ""};
  c_actual::Box b{0.f, 0.f, 10.f, 10.f, 1.f, 0, ""};
  check(std::fabs(c_actual::postprocess::iou(a, b) - 1.0f) < 1e-6f, "identical boxes give IoU 1");
  c_actual::Box c{20.f, 20.f, 10.f, 10.f, 1.f, 0, ""};
  check(c_actual::postprocess::iou(a, c) == 0.f, "disjoint boxes give IoU 0");
  c_actual::Box d{0.f, 0.f, 0.f, 0.f, 1.f, 0, ""};
  check(c_actual::postprocess::iou(d, d) == 0.f, "degenerate zero-area boxes give IoU 0");
}

void testEndToEnd() {
  std::cout << "end-to-end (needs models)\n";
  const char *dir = std::getenv("C_ACTUAL_MODELS_DIR");
  if (!dir) {
    std::cout << "  [SKIP] C_ACTUAL_MODELS_DIR not set\n";
    return;
  }
  const std::string root(dir);
  c_actual::ModelPaths paths;
  paths.ball_track = root + "/balltrack_tracknetv3.onnx";
  paths.hand = root + "/hand_yolov8n_gray.onnx";
  paths.racket = root + "/racket_yolov8n.onnx";

  c_actual::Config config;
  c_actual::CPerceptionEngine engine;
  std::string error;
  if (!engine.load(paths, config, &error)) {
    std::cout << "  [SKIP] models not loadable: " << error << "\n";
    return;
  }
  check(true, "all three models load");

  // A synthetic gray8 frame. The ball must report WARMUP for the first frames
  // and the engine must never duplicate frames to fake history.
  cv::Mat gray(720, 1280, CV_8UC1);
  cv::randu(gray, cv::Scalar(0), cv::Scalar(255));
  c_actual::FrameMeta meta;
  int warmups = 0;
  for (int i = 0; i <= config.ball_seq_len; ++i) {
    meta.frame_id = static_cast<uint64_t>(i);
    const auto result = engine.inferGray(gray, meta);
    if (result.ball.state == c_actual::BallState::kWarmup) ++warmups;
  }
  check(warmups == config.ball_seq_len, "ball reports WARMUP until real history exists");

  meta.frame_id = 100;
  const auto after = engine.inferGray(gray, meta);
  check(after.ball.state != c_actual::BallState::kWarmup,
        "ball leaves WARMUP once the official window is full");
  check(after.width == 1280 && after.height == 720, "result carries the original size");
}

void testBallTrackWindowBookkeeping() {
  std::cout << "BallTrack window bookkeeping (engine-level, no model needed)" << std::endl;
  // Without models the engine cannot load, so this exercises the standalone
  // engine only when models are available; the pure window arithmetic is
  // asserted by testBallTrackChannelLayoutWithModels below.
  const char *dir = std::getenv("C_ACTUAL_MODELS_DIR");
  if (!dir) {
    std::cout << "  [SKIP] C_ACTUAL_MODELS_DIR not set" << std::endl;
    return;
  }
  const std::string root(dir);
  c_actual::ModelPaths paths;
  paths.ball_track = root + "/balltrack_tracknetv3.onnx";
  paths.hand = root + "/hand_yolov8n_gray_final_v3_960.onnx";
  paths.racket = root + "/racket_yolov8n_gray.onnx";
  c_actual::Config config;
  c_actual::CPerceptionEngine engine;
  std::string error;
  if (!engine.load(paths, config, &error)) {
    std::cout << "  [SKIP] models not loadable: " << error << std::endl;
    return;
  }

  cv::Mat gray(720, 1280, CV_8UC1, cv::Scalar(10));
  c_actual::FrameMeta meta;
  int warmups = 0;
  for (int i = 0; i < 4; ++i) {
    meta.frame_id = static_cast<uint64_t>(i);
    const auto r = engine.inferGray(gray, meta);
    if (r.ball.state == c_actual::BallState::kWarmup) ++warmups;
  }
  check(warmups == 4, "frames 1..4 report WARMUP (need seq_len real predecessors)");

  meta.frame_id = 4;
  const auto fifth = engine.inferGray(gray, meta);
  check(fifth.ball.state != c_actual::BallState::kWarmup,
        "frame 5 leaves WARMUP and runs the model");
  // A uniform frame carries no ball, so the model must not invent one.
  check(fifth.ball.state == c_actual::BallState::kDropout ||
            fifth.ball.state == c_actual::BallState::kDetected,
        "frame 5 reports a real model outcome (DROPOUT or DETECTED), not INVALID");

  engine.reset();
  meta.frame_id = 0;
  const auto after_reset = engine.inferGray(gray, meta);
  check(after_reset.ball.state == c_actual::BallState::kWarmup,
        "reset() clears history and background so the next clip starts in WARMUP");
}

void testBallTrackChannelLayoutWithModels() {
  std::cout << "BallTrack 15-channel layout and temporal window" << std::endl;
  const char *dir = std::getenv("C_ACTUAL_MODELS_DIR");
  if (!dir) {
    std::cout << "  [SKIP] C_ACTUAL_MODELS_DIR not set" << std::endl;
    return;
  }
  const std::string root(dir);
  c_actual::ModelPaths paths;
  paths.ball_track = root + "/balltrack_tracknetv3.onnx";
  paths.hand = root + "/hand_yolov8n_gray_final_v3_960.onnx";
  paths.racket = root + "/racket_yolov8n_gray.onnx";
  c_actual::Config config;
  c_actual::CPerceptionEngine engine;
  std::string error;
  if (!engine.load(paths, config, &error)) {
    std::cout << "  [SKIP] models not loadable: " << error << std::endl;
    return;
  }

  // Constant-valued frames so resize and /255 cannot blur channel identity.
  // We feed frames 1..5 and then read the tensor the engine would use for the
  // NEXT frame: debugBallInput() is defined as "the window for the upcoming
  // inference", so it must be read at the point in time we want to inspect.
  const int values[5] = {10, 20, 30, 40, 50};
  cv::Mat gray(720, 1280, CV_8UC1);
  c_actual::FrameMeta meta;
  for (int i = 0; i < 5; ++i) {
    gray.setTo(cv::Scalar(values[i]));
    meta.frame_id = static_cast<uint64_t>(i);
    engine.inferGray(gray, meta);
  }

  // Frame 5 was just SCORED from window [1,2,3,4] = [10,20,30,40]. The window
  // has since slid to [2,3,4,5] = [20,30,40,50] for the NEXT frame (6), and
  // frame 6 itself has not been seen yet, so 60 must be absent.
  const std::vector<float> tensor = engine.debugBallInput();
  const int W = config.ball_width, H = config.ball_height;
  const int plane = H * W;
  check(tensor.size() == static_cast<size_t>(15) * plane,
        "tensor has exactly 15 * H * W floats");

  // Expected: background(frame1=10) then frames 2..5 -> 20,30,40,50.
  // Frame 6 (60) must NOT appear: that would be current-frame leakage.
  const int expected[5] = {10, 20, 30, 40, 50};
  bool layout_ok = true;
  for (int item = 0; item < 5; ++item) {
    for (int c = 0; c < 3; ++c) {
      const int channel = item * 3 + c;
      const float v = tensor[static_cast<size_t>(channel) * plane + 5];
      const float want = expected[item] / 255.0f;
      if (std::fabs(v - want) > 1e-4f) layout_ok = false;
    }
  }
  if (!layout_ok) {
    std::cout << "  [diag] per-channel value at pixel 5 (expected x/255):" << std::endl;
    for (int channel = 0; channel < 15; ++channel) {
      const float v = tensor[static_cast<size_t>(channel) * plane + 5];
      std::cout << "    ch" << channel << " = " << v << "  (= " << (v * 255.0f) << " in 0..255)"
                << std::endl;
    }
  }
  check(layout_ok, "channels = [bg(10)|20|30|40|50] x RGB, gray copied 3x each");

  bool has_60 = false;
  for (float v : tensor) {
    if (std::fabs(v - 60.0f / 255.0f) < 1e-5f) has_60 = true;
  }
  check(!has_60, "the yet-unseen frame 6 (60) is not in the upcoming window");
}
void testPerDetectorInputSize() {
  std::cout << "per-detector ONNX input size (hand 960 vs racket 640)" << std::endl;
  const char *dir = std::getenv("C_ACTUAL_MODELS_960_DIR");
  if (!dir) {
    std::cout << "  [SKIP] C_ACTUAL_MODELS_960_DIR not set" << std::endl;
    return;
  }
  const std::string root(dir);
  // Accept either the shipped package names or the short names used by earlier
  // scratch directories, so the test can run against a delivered ZIP as-is.
  const auto pick = [&root](const std::vector<std::string> &candidates) {
    for (const auto &name : candidates) {
      const std::string full = root + "/" + name;
      if (std::ifstream(full).good()) return full;
    }
    return root + "/" + candidates.front();
  };
  c_actual::ModelPaths paths;
  paths.ball_track = pick({"balltrack_tracknetv3.onnx", "ball.onnx"});
  paths.hand = pick({"hand_yolov8n_gray_final_v3_960.onnx",
                     "hand_yolov8n_gray_final_v2_960.onnx", "hand960.onnx"});
  paths.racket = pick({"racket_yolov8n_gray.onnx", "racket640.onnx"});
  c_actual::Config config;
  c_actual::CPerceptionEngine engine;
  std::string error;
  if (!engine.load(paths, config, &error)) {
    check(false, std::string("engine should load mixed 960/640 models: ") + error);
    return;
  }
  // Each detector must take its size from its own graph, not from Config::imgsz.
  check(engine.debugHandInputSize() == 960, "hand input size is 960 (from its ONNX shape)");
  check(engine.debugRacketInputSize() == 640,
        "racket input size is 640 (from its ONNX shape)");
  check(engine.debugHandInputSize() != engine.debugRacketInputSize(),
        "the two detectors use independent resolutions");

  // A real inference must not surface an input-shape error. If the engine still
  // fed a 640 tensor to the 960 graph, this is the regression that would show up.
  cv::Mat gray(720, 1280, CV_8UC1, cv::Scalar(114));
  c_actual::FrameMeta meta;
  const auto result = engine.inferGray(gray, meta);
  bool reported_error = false;
  for (const auto &w : result.warnings) {
    if (w.find("MISMATCH") != std::string::npos ||
        w.find("YOLO_INFERENCE_FAILED") != std::string::npos ||
        w.find("INVALID") != std::string::npos) {
      reported_error = true;
    }
  }
  check(!reported_error, "no input-shape/inference error for the 960 hand model");
}
}  // namespace

int main() {
  std::cout << "c_actual tests\n";
  testGray3();
  testLetterbox();
  testUnletterbox();
  testNms();
  testIou();
  testEndToEnd();
  testBallTrackWindowBookkeeping();
  testBallTrackChannelLayoutWithModels();
  testPerDetectorInputSize();


  std::cout << "\n" << (checks - failures) << "/" << checks << " checks passed\n";
  if (failures) {
    std::cout << failures << " FAILED\n";
    return 1;
  }
  std::cout << "ALL PASS\n";
  return 0;
}
