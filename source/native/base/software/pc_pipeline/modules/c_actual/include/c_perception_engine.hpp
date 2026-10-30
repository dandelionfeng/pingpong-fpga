// C perception engine v2 - gray3 ONNX Runtime inference, captain-facing API.
//
// Design contract (frozen for the C HANDOFF V2 deliverable):
//
//   * Input is ALWAYS a single-channel 8-bit grayscale image (CV_8UC1).
//     The caller never does gray->3ch, resize, letterbox or normalization.
//   * Every model is fed a gray3 tensor derived from that one GRAY8 frame,
//     matching the OV9281 chain the A side actually delivers.
//   * Outputs are in ORIGINAL image coordinates of the GRAY8 frame handed in.
//   * BallTrack is temporal: frames are pushed one at a time and internally
//     buffered. Until the official window is full the ball reports WARMUP -
//     the engine never duplicates a frame to fake history.
//   * Hand role (toss/racket) is B's job. This module emits raw hand boxes only.

#ifndef C_ACTUAL_PERCEPTION_ENGINE_HPP
#define C_ACTUAL_PERCEPTION_ENGINE_HPP

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <opencv2/core.hpp>

namespace c_actual {

// ------------------------------------------------------------------ model io
struct ModelPaths {
  std::string ball_track;    // balltrack_tracknetv3.onnx (temporal, gray3)
  std::string hand;          // hand_yolov8n_gray.onnx     (1 class: hand)
  std::string racket;        // racket model onnx          (class: racket)
  // OPTIONAL single 3-class detector (ball=0 / hand=1 / racket=2).
  //
  // When this path is non-empty the engine runs ONE YOLO inference per frame and
  // serves BOTH hand and racket from it; `hand` and `racket` above are then
  // ignored (they may stay empty). The class ids of this graph are fixed and are
  // validated at load time: 0=ball, 1=hand, 2=racket.
  //
  // In legacy hybrid mode, this graph's ball class is NOT used: BallTrack is the ball
  // source in the frozen interface (see INTERFACE_CONTRACT.md). A YOLO ball box
  // would be a second, differently-defined ball observation and would silently
  // compete with BallTrack.
  std::string unified;
  // Local opt-in extension: this graph is the ONLY model for all three classes.
  // Ball detections are proposals in `balls`, never heatmap centers in `ball`.
  bool unified_all_classes = false;
  // Optional: if empty, the ball/racket classes are read from the model itself.
  std::string ball_class_name = "ball";
  std::string racket_class_name = "racket";
};

struct Config {
  // YOLO detector
  int imgsz = 640;
  float iou = 0.50f;
  float base_conf = 0.02f;   // inference floor: one pass caches all candidates
  float hand_conf = 0.25f;   // accept threshold for hand boxes
  float racket_conf = 0.25f; // accept threshold for racket boxes
  float yolo_ball_conf = 0.20f; // single-YOLO experiment; distinct from heatmap score
  int max_det = 100;

  // BallTrack (official TrackNetV3 contract)
  int ball_seq_len = 4;      // frames of context BEFORE the scored frame
  int ball_width = 512;
  int ball_height = 288;
  float ball_heatmap_threshold = 0.5f;
  float ball_conf_min = 0.5f;

  // Execution
  int intra_op_threads = 0;  // 0 = ORT default
  bool use_cuda = false;     // CPU provider always works; CUDA is optional
  bool verbose = false;
};

struct FrameMeta {
  uint64_t frame_id = 0;
  double timestamp = 0.0;
  int64_t submitted_ns = 0;
  bool has_reference = false;
  uint64_t reference_id = 0;
  int64_t reference_timestamp_ns = 0;
};

// ---------------------------------------------------------------- inference
struct Box {
  float x = 0.f, y = 0.f, w = 0.f, h = 0.f;  // top-left + size, original coords
  float confidence = 0.f;
  int class_id = 0;
  std::string class_name;
};

enum class BallState {
  kDetected,         // heatmap component accepted in THIS frame (legacy ball API)
  kWarmup,           // not enough history yet; no prediction made
  kDropout,          // window full but heatmap below threshold this frame
  kInvalid,          // error / model unavailable
};

const char *to_string(BallState state);

struct BallResult {
  BallState state = BallState::kInvalid;
  bool detected = false;
  float confidence = 0.f;
  cv::Point2f center{0.f, 0.f};   // canonical output, original coords
  bool has_region = false;        // true when a heatmap component gave bounds
  cv::Rect2f region;              // heatmap component bounds (NOT a fitted box)
  // bbox_semantics is "heatmap_component" when has_region; the canonical ball
  // output is the center. A caller must not treat region as a tight ball box.
  std::string bbox_semantics = "none";
};

struct PerceptionResult {
  FrameMeta meta;
  int width = 0, height = 0;
  BallResult ball; // legacy BallTrack only; unused in unified_all_classes mode
  std::vector<Box> balls; // detector boxes only; B must refine a pixel center
  std::vector<Box> hands;
  std::vector<Box> rackets;
  std::vector<std::string> warnings;
  double infer_ms = 0.0;
  std::string ball_model, hand_model, racket_model;
  // Non-empty when a unified 3-class model served hand+racket (optionally ball).
  // hand_model and racket_model both point at this same graph, and exactly one
  // YOLO inference ran for the frame.
  std::string unified_model;
};

// ------------------------------------------------------------------- engine
class CPerceptionEngine {
 public:
  CPerceptionEngine();
  ~CPerceptionEngine();

  CPerceptionEngine(const CPerceptionEngine &) = delete;
  CPerceptionEngine &operator=(const CPerceptionEngine &) = delete;

  // Legacy modes require BallTrack plus the specialist or unified detectors.
  // unified_all_classes requires exactly one unified path, with no specialists.
  // Returns false and fills `error` on failure.
  bool load(const ModelPaths &paths, const Config &config, std::string *error);

  // One gray8 frame in, one perception result out. Requires gray.type() ==
  // CV_8UC1. Internally derived gray3 is used for every model.
  PerceptionResult inferGray(const cv::Mat &gray, const FrameMeta &meta);

  // Capture-side causal window; unchanged BallTrack tensor values/order.
  PerceptionResult inferGrayWindow(const cv::Mat &gray, const FrameMeta &meta,
      const cv::Mat &background, const std::vector<cv::Mat> &preceding);

  // Clears the BallTrack history AND the frozen background (call between
  // unrelated video clips, or after a camera restart).
  void reset();

  // Validation hook: the BallTrack input tensor for the current window, laid out
  // as [1, 3*(seq_len+1), H, W] flattened. Lets tests assert the 15-channel
  // contract and compare against the Python reference without running a model.
  std::vector<float> debugBallInput() const;

  // Diagnostic: the square input resolution each detector derived from its OWN
  // ONNX graph. Proves hand and racket are independent (e.g. 960 vs 640) and
  // that no single global imgsz is applied to both. When a unified model is
  // loaded, both report the unified graph's size (one graph serves both classes).
  int debugHandInputSize() const;
  int debugRacketInputSize() const;
  // True when hand+racket come from ONE 3-class graph instead of two detectors.
  bool usingUnifiedDetector() const;
  bool usingUnifiedBallDetector() const;

  const Config &config() const;
  const ModelPaths &paths() const;
  // "model_version" strings for the handoff reports.
  std::string versionString() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

// Shared helpers (exposed for tests).
namespace preprocess {
// GRAY8 -> 3 identical channels. Values are equal so BGR/RGB order is moot.
cv::Mat grayToGray3(const cv::Mat &gray);
// Ultralytics letterbox: preserves aspect ratio, pads with 114.
cv::Mat letterbox(const cv::Mat &bgr, int size, float *scale_out, int *pad_x_out,
                  int *pad_y_out);
}  // namespace preprocess

namespace postprocess {
// Map a letterboxed detection back to original image coordinates.
Box unletterbox(float cx, float cy, float w, float h, float confidence, int class_id,
                float scale, int pad_x, int pad_y, int image_w, int image_h);
float iou(const Box &a, const Box &b);
std::vector<Box> nms(std::vector<Box> boxes, float iou_threshold, int max_det);
}  // namespace postprocess

}  // namespace c_actual

#endif  // C_ACTUAL_PERCEPTION_ENGINE_HPP
