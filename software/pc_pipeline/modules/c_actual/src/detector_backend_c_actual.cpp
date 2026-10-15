// Bridge from the repo's DetectorBackend ABI to the c_actual C++ engine.
//
// Contract notes (read before changing):
//
//   * This file belongs to the pc_pipeline target, which also compiles
//     pipeline.hpp (cv::Mat + Json + Meta). It is NOT part of the standalone
//     c_actual target, which stays ONNX Runtime + OpenCV only.
//
//   * DetectorContext::gray is ALREADY the eye-space GRAY8 image (CV_8UC1) that
//     the A side delivers, which is exactly what CPerceptionEngine::inferGray
//     expects. No conversion happens here, and the engine does gray3 internally.
//
//   * DetectionResult::boxes carries the repo's JSON schema:
//         {"class": "ball"|"hand"|"racket", "confidence": 0..1,
//          "bbox": [x, y, w, h]}
//     All coordinates are original-eye pixels.
//
//   * HAND entries are REAL YOLO hand boxes. This code never derives a hand box
//     from a wrist keypoint; the wrist path was retired (see
//     FINAL_ARCHITECTURE.md).
//
//   * Hand ROLE (toss hand vs racket hand) is deliberately NOT decided here.
//     That needs temporal context and belongs to module B.
//
//   * BallTrack is temporal, so this backend keeps one engine per eye. Results
//     are still produced per frame; the engine returns WARMUP until its window
//     is full and never duplicates a frame.

#include "pipeline/pipeline.hpp"

#include "c_perception_engine.hpp"

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace pipeline {
namespace {

Json boxToJson(const char *cls, double confidence, const c_actual::Box &box) {
  Json entry;
  entry["class"] = cls;
  entry["confidence"] = confidence;
  entry["bbox"] = Json::array({box.x, box.y, box.w, box.h});
  return entry;
}

// BallTrack's canonical output is a CENTER. The legacy schema only has bbox, so
// we emit the heatmap component bounds when available and fall back to a
// zero-area box at the center. `ball_center` is exposed in the extra metadata so
// B can read the true center, and `bbox_semantics` says which case this is - we
// never pass a fabricated tight ball box off as a real detection box.
Json ballToJson(const c_actual::BallResult &ball) {
  Json entry;
  entry["class"] = "ball";
  entry["confidence"] = ball.detected ? ball.confidence : 0.0;
  entry["state"] = c_actual::to_string(ball.state);
  entry["detected"] = ball.detected;
  entry["ball_center"] = Json::array({ball.center.x, ball.center.y});
  if (ball.has_region) {
    entry["bbox"] = Json::array({ball.region.x, ball.region.y, ball.region.width,
                                 ball.region.height});
    entry["bbox_semantics"] = "heatmap_component";
  } else {
    // Center-only: a zero-size box keeps the schema valid without inventing size.
    entry["bbox"] = Json::array({ball.center.x, ball.center.y, 0.0, 0.0});
    entry["bbox_semantics"] = "center_only";
  }
  return entry;
}

}  // namespace

// ---------------------------------------------------------------------------
// CActualConfig
// ---------------------------------------------------------------------------
struct CActualConfig {
  std::string ball_model;
  std::string hand_model;
  std::string racket_model;
  float base_conf = 0.02f;
  float hand_conf = 0.25f;
  float racket_conf = 0.30f;
  bool use_cuda = false;
  bool verbose = false;

  bool complete() const {
    return !ball_model.empty() && !hand_model.empty() && !racket_model.empty();
  }
};

// ---------------------------------------------------------------------------
// CPerceptionDetector - DetectorBackend backed by the real ONNX models
// ---------------------------------------------------------------------------
class CPerceptionDetector final : public DetectorBackend {
 public:
  CPerceptionDetector(CActualConfig config, std::string left_racket_class,
                      std::string right_racket_class)
      : config_(std::move(config)),
        left_racket_class_(std::move(left_racket_class)),
        right_racket_class_(std::move(right_racket_class)) {}

  // Loads the models. Returns false with `error` filled; the caller decides
  // whether to surface an unavailable backend instead of failing the run.
  bool load(std::string *error) {
    c_actual::ModelPaths paths;
    paths.ball_track = config_.ball_model;
    paths.hand = config_.hand_model;
    paths.racket = config_.racket_model;

    c_actual::Config config;
    config.base_conf = config_.base_conf;
    config.hand_conf = config_.hand_conf;
    config.racket_conf = config_.racket_conf;
    config.use_cuda = config_.use_cuda;
    config.verbose = config_.verbose;

    std::lock_guard<std::mutex> lock(mutex_);
    // One engine per eye: BallTrack history must not mix the two cameras.
    for (auto *engine : {&left_, &right_}) {
      if (!engine->load(paths, config, error)) {
        return false;
      }
    }
    loaded_ = true;
    return true;
  }

  DetectionResult infer(const DetectorContext &context, const std::atomic<bool> &stop,
                        int timeoutMs) override {
    const auto started = std::chrono::steady_clock::now();

    DetectionResult result;
    result.meta = context.meta;
    result.eye = context.eye;
    result.task_id = context.task_id;
    result.generation = context.generation;
    result.reference_id = context.reference_id;
    result.reference_timestamp_ns = context.reference_timestamp_ns;
    result.reference_valid = context.reference_valid;
    result.backend = mode();

    if (stop.load()) {
      result.status = "cancelled";
      return result;
    }
    if (!loaded_) {
      result.status = "unavailable: models not loaded";
      return result;
    }
    if (context.gray.empty()) {
      result.status = "invalid: empty gray frame";
      return result;
    }
    // The engine itself enforces CV_8UC1; check here too so the failure is
    // reported as a status instead of an exception crossing the ABI.
    if (context.gray.type() != CV_8UC1) {
      result.status = "invalid: context.gray must be CV_8UC1 (GRAY8)";
      return result;
    }

    c_actual::FrameMeta meta;
    // The pipeline Meta is pair-oriented: pair_id, a pair timestamp in ns, and
    // per-eye timestamps/frame ids indexed by eye.
    const size_t eye_index = (context.eye == Eye::Right) ? 1 : 0;
    meta.frame_id = context.meta.camera_frame_id[eye_index];
    const int64_t eye_ns = context.meta.eye_timestamp_ns[eye_index] > 0
                               ? context.meta.eye_timestamp_ns[eye_index]
                               : context.meta.timestamp_ns;
    meta.timestamp = static_cast<double>(eye_ns) / 1e9;
    meta.submitted_ns = context.submitted_ns;
    meta.has_reference = context.reference_valid[eye_index];
    meta.reference_id = context.reference_id[eye_index];
    meta.reference_timestamp_ns = context.reference_timestamp_ns[eye_index];

    c_actual::PerceptionResult perception;
    try {
      std::lock_guard<std::mutex> lock(mutex_);
      c_actual::CPerceptionEngine &engine = (context.eye == Eye::Right) ? right_ : left_;
      perception = engine.inferGray(context.gray, meta);
    } catch (const std::exception &exc) {
      result.status = std::string("invalid: ") + exc.what();
      result.boxes = Json::array();
      return result;
    }

    // Deadline: the models are synchronous, so we can only report an overrun.
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::steady_clock::now() - started)
                             .count();
    if (timeoutMs > 0 && elapsed > timeoutMs) {
      result.status = "timeout: inference exceeded the deadline";
    } else if (stop.load()) {
      result.status = "cancelled";
    } else {
      result.status = "ok";
    }

    Json boxes = Json::array();

    // ball (always present; state tells the caller whether it is a detection)
    boxes.push_back(ballToJson(perception.ball));

    // hands: real YOLO boxes, no role assignment
    for (const auto &hand : perception.hands) {
      boxes.push_back(boxToJson("hand", hand.confidence, hand));
    }

    // rackets
    for (const auto &racket : perception.rackets) {
      boxes.push_back(boxToJson("racket", racket.confidence, racket));
    }

    result.boxes = boxes;
    result.meta.model_version =
        "c_actual-v2|balltrack-gray3|hand-yolov8n-gray3|racket-yolov8n-gray3";
    return result;
  }

  std::string mode() const override { return "actual-model-c-actual-v2"; }

 private:
  CActualConfig config_;
  std::string left_racket_class_;
  std::string right_racket_class_;
  c_actual::CPerceptionEngine left_;
  c_actual::CPerceptionEngine right_;
  std::mutex mutex_;
  bool loaded_ = false;
};

// ---------------------------------------------------------------------------
// Factory used by the registry / runner
// ---------------------------------------------------------------------------
std::unique_ptr<DetectorBackend> makeCActualDetector(const CActualConfig &config,
                                                     std::string *error) {
  auto detector = std::make_unique<CPerceptionDetector>(config, "left", "right");
  if (!detector->load(error)) {
    return nullptr;
  }
  return detector;
}

// A backend that reports why the actual models are unavailable, so the pipeline
// keeps running instead of crashing when the ONNX files are absent.
std::unique_ptr<DetectorBackend> unavailableCActualDetector(const std::string &reason) {
  class Unavailable final : public DetectorBackend {
   public:
    explicit Unavailable(std::string reason) : reason_(std::move(reason)) {}
    DetectionResult infer(const DetectorContext &context, const std::atomic<bool> &,
                          int) override {
      DetectionResult result;
      result.meta = context.meta;
      result.eye = context.eye;
      result.task_id = context.task_id;
      result.generation = context.generation;
      result.backend = mode();
      result.status = reason_;
      result.boxes = Json::array();
      return result;
    }
    std::string mode() const override { return "actual-model-unavailable"; }

   private:
    std::string reason_;
  };
  return std::make_unique<Unavailable>(reason);
}

}  // namespace pipeline
