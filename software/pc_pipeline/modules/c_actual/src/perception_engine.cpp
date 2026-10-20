#include "c_perception_engine.hpp"

#include <chrono>
#include <cstdio>
#include <stdexcept>

#include "internal_onnx.hpp"

namespace c_actual {

const char *to_string(BallState state) {
  switch (state) {
    case BallState::kDetected:
      return "DETECTED";
    case BallState::kWarmup:
      return "WARMUP";
    case BallState::kDropout:
      return "DROPOUT";
    case BallState::kInvalid:
    default:
      return "INVALID";
  }
}

struct CPerceptionEngine::Impl {
  Config config;
  ModelPaths paths;
  BallTrack ball;
  YoloDetector hand;
  YoloDetector racket;
  YoloDetector unified;   // optional single 3-class detector
  bool ball_loaded = false;
  bool hand_loaded = false;
  bool racket_loaded = false;
  bool unified_loaded = false;
};

CPerceptionEngine::CPerceptionEngine() : impl_(new Impl()) {}
CPerceptionEngine::~CPerceptionEngine() {
  // Release ONNX Runtime sessions before the process tears down static state.
  if (impl_) {
    impl_->ball.release();
    impl_->hand.release();
    impl_->racket.release();
    impl_->unified.release();
  }
}

const Config &CPerceptionEngine::config() const { return impl_->config; }
const ModelPaths &CPerceptionEngine::paths() const { return impl_->paths; }

bool CPerceptionEngine::load(const ModelPaths &paths, const Config &config, std::string *error) {
  impl_->config = config;
  impl_->paths = paths;

  if (paths.ball_track.empty()) {
    if (error) *error = "MISSING_MODEL: ball_track model path is empty";
    return false;
  }
  std::string local_error;
  impl_->ball_loaded = impl_->ball.load(paths.ball_track, config, config.use_cuda, &local_error);
  if (!impl_->ball_loaded) {
    if (error) *error = "MISSING_MODEL or invalid ball model '" + paths.ball_track +
                        "': " + local_error;
    return false;
  }

  // ---- optional unified 3-class detector --------------------------------
  // Loaded INSTEAD OF the two separate detectors. The class order of the graph
  // is part of the model contract (0=ball, 1=hand, 2=racket) and is checked here
  // so a wrong graph cannot silently deliver racket boxes as hands.
  if (!paths.unified.empty()) {
    impl_->unified_loaded = impl_->unified.load(
        paths.unified, {"ball", "hand", "racket"}, config, config.use_cuda, &local_error);
    if (!impl_->unified_loaded) {
      if (error) *error = "MISSING_MODEL or invalid unified model '" + paths.unified +
                          "': " + local_error;
      return false;
    }
    const int declared = impl_->unified.numClasses();
    if (declared != 0 && declared != 3) {
      impl_->unified.release();
      impl_->unified_loaded = false;
      if (error) {
        *error = "UNIFIED_MODEL_CLASS_MISMATCH: expected 3 classes "
                 "(0=ball, 1=hand, 2=racket) but the graph declares " +
                 std::to_string(declared);
      }
      return false;
    }
    // The separate paths are ignored on purpose; make that visible rather than
    // silently mixing three models into one frame.
    if (!paths.hand.empty() || !paths.racket.empty()) {
      std::fprintf(stderr,
                   "[c_actual] unified model is set: the --hand-model/--racket-model "
                   "paths are ignored\n");
    }
    return true;
  }

  if (paths.hand.empty()) {
    if (error) *error = "MISSING_MODEL: hand model path is empty";
    return false;
  }
  // Hand model is a 1-class detector.
  impl_->hand_loaded = impl_->hand.load(paths.hand, {"hand"}, config, config.use_cuda, &local_error);
  if (!impl_->hand_loaded) {
    if (error) *error = "MISSING_MODEL or invalid hand model '" + paths.hand +
                        "': " + local_error;
    return false;
  }

  if (paths.racket.empty()) {
    if (error) *error = "MISSING_MODEL: racket model path is empty";
    return false;
  }
  // The racket ONNX may be the combined 2-class ball+racket model or a
  // racket-only model; class_names only affects the reported name.
  impl_->racket_loaded =
      impl_->racket.load(paths.racket, {"ball", "racket"}, config, config.use_cuda, &local_error);
  if (!impl_->racket_loaded) {
    if (error) *error = "MISSING_MODEL or invalid racket model '" + paths.racket +
                        "': " + local_error;
    return false;
  }

  return true;
}

void CPerceptionEngine::reset() {
  // Clears temporal history, the frozen background and the frame counter so the
  // next clip starts clean. The left and right engines are separate objects, so
  // histories never mix between eyes.
  impl_->ball.reset();
}

int CPerceptionEngine::debugHandInputSize() const {
  return impl_->unified_loaded ? impl_->unified.imgsz() : impl_->hand.imgsz();
}

int CPerceptionEngine::debugRacketInputSize() const {
  return impl_->unified_loaded ? impl_->unified.imgsz() : impl_->racket.imgsz();
}

bool CPerceptionEngine::usingUnifiedDetector() const { return impl_->unified_loaded; }

std::vector<float> CPerceptionEngine::debugBallInput() const {
  return impl_->ball.buildInputForTest();
}

std::string CPerceptionEngine::versionString() const {
  if (impl_->unified_loaded) {
    return "c_actual-v2.4-unified | ball=balltrack-gray3 | "
           "hand+racket=unified-3class-gray3@" + std::to_string(impl_->unified.imgsz());
  }
  return "c_actual-v2.3-interface | ball=balltrack-gray3 | "
         "hand=yolov8n-hand-gray3@960 | racket=yolov8n-racket-gray3@640";
}

PerceptionResult CPerceptionEngine::inferGray(const cv::Mat &gray, const FrameMeta &meta) {
  const auto started = std::chrono::steady_clock::now();

  if (gray.empty()) {
    throw std::invalid_argument("inferGray: empty image");
  }
  if (gray.type() != CV_8UC1) {
    throw std::invalid_argument(
        "inferGray: input must be CV_8UC1 (single-channel uint8 grayscale); the engine "
        "performs gray3 conversion and all model preprocessing internally");
  }

  PerceptionResult result;
  result.meta = meta;
  result.width = gray.cols;
  result.height = gray.rows;
  result.ball_model = impl_->paths.ball_track;
  if (impl_->unified_loaded) {
    // One graph serves both classes; reporting it in both fields keeps the
    // model_version output truthful.
    result.unified_model = impl_->paths.unified;
    result.hand_model = impl_->paths.unified;
    result.racket_model = impl_->paths.unified;
  } else {
    result.hand_model = impl_->paths.hand;
    result.racket_model = impl_->paths.racket;
  }

  // One gray3 derivation per frame; every model consumes it.
  const cv::Mat gray3 = preprocess::grayToGray3(gray);

  // ---- ball (temporal) ----
  result.ball = impl_->ball.push(gray);
  if (result.ball.state == BallState::kWarmup) {
    result.warnings.push_back(
        "ball WARMUP: BallTrack needs " + std::to_string(impl_->config.ball_seq_len) +
        " frames of real history; no prediction was made and no frame was duplicated");
  }

  if (impl_->unified_loaded) {
    // ---- hand + racket from ONE inference pass ----
    std::string unified_error;
    std::vector<Box> raw =
        impl_->unified.detect(gray3, impl_->config.base_conf, gray.cols, gray.rows,
                              &unified_error);
    if (!unified_error.empty()) {
      result.warnings.push_back("unified " + unified_error);
      std::fprintf(stderr, "[c_actual] unified detector error: %s\n", unified_error.c_str());
    }
    for (Box &box : raw) {
      if (box.class_name == "hand") {
        if (box.confidence >= impl_->config.hand_conf) {
          box.class_name = "hand";
          result.hands.push_back(box);
        }
      } else if (box.class_name == "racket") {
        if (box.confidence >= impl_->config.racket_conf) {
          box.class_name = "racket";
          result.rackets.push_back(box);
        }
      }
      // "ball" is intentionally dropped: the frozen interface has exactly one
      // ball source (BallTrack). Emitting a second, differently-defined ball box
      // would silently compete with it in module B.
    }
    const auto finished = std::chrono::steady_clock::now();
    result.infer_ms =
        std::chrono::duration_cast<std::chrono::duration<double, std::milli>>(finished -
                                                                             started)
            .count();
    return result;
  }

  // ---- hand (single inference pass at base_conf, threshold applied after) ----
  if (impl_->hand_loaded) {
    std::string hand_error;
    std::vector<Box> raw =
        impl_->hand.detect(gray3, impl_->config.base_conf, gray.cols, gray.rows, &hand_error);
    if (!hand_error.empty()) {
      // Never let a detector failure look like "no hands in this frame".
      result.warnings.push_back("hand " + hand_error);
      std::fprintf(stderr, "[c_actual] hand detector error: %s\n", hand_error.c_str());
    }
    for (Box &box : raw) {
      if (box.confidence >= impl_->config.hand_conf) {
        box.class_name = "hand";
        result.hands.push_back(box);
      }
    }
    // Raw hand role assignment (toss vs racket hand) is intentionally NOT done
    // here: that needs temporal context and belongs to module B.
  }

  // ---- racket ----
  if (impl_->racket_loaded) {
    std::string racket_error;
    std::vector<Box> raw =
        impl_->racket.detect(gray3, impl_->config.base_conf, gray.cols, gray.rows, &racket_error);
    if (!racket_error.empty()) {
      result.warnings.push_back("racket " + racket_error);
      std::fprintf(stderr, "[c_actual] racket detector error: %s\n", racket_error.c_str());
    }
    for (Box &box : raw) {
      const bool is_racket = (box.class_name == "racket") ||
                             (box.class_id == 1 && impl_->racket.classNames().size() > 1);
      if (!is_racket) continue;  // ball class of the combined model is not used here
      if (box.confidence >= impl_->config.racket_conf) {
        box.class_name = "racket";
        result.rackets.push_back(box);
      }
    }
  }

  const auto finished = std::chrono::steady_clock::now();
  result.infer_ms =
      std::chrono::duration_cast<std::chrono::duration<double, std::milli>>(finished - started)
          .count();
  return result;
}

}  // namespace c_actual
