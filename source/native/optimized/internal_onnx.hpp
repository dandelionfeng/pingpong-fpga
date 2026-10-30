// Shared ONNX Runtime plumbing + the YOLO detector and the temporal BallTrack
// wrapper. Internal headers; not part of the captain-facing API.

#ifndef C_ACTUAL_INTERNAL_ONNX_HPP
#define C_ACTUAL_INTERNAL_ONNX_HPP

#include "runtime_session.hpp"

#include <cstdint>
#include <deque>
#include <string>
#include <vector>

#include <opencv2/core.hpp>

#include "c_perception_engine.hpp"

namespace c_actual {

// ------------------------------------------------------------------ session
// NCHW float tensor from a BGR (or gray3) image, RGB order, 0..1 range.
std::vector<float> imageToNchw(const cv::Mat &bgr, int size);

// ------------------------------------------------------------- YOLO detector
class YoloDetector {
 public:
  // `class_names` maps class index -> name (e.g. {0: "hand"} or {0:"ball",1:"racket"}).
  //
  // The square input resolution is read from THIS model's own input shape, so a
  // 960 hand model and a 640 racket model can coexist without a global setting.
  bool load(const std::string &path, const std::vector<std::string> &class_names,
            const Config &config, bool use_cuda, std::string *error);

  bool ok() const { return session_.ok(); }

  // Square input resolution actually used, derived from the ONNX input shape.
  int imgsz() const { return imgsz_; }

  // Number of classes declared by the output channel count (shape[1] - 4).
  // Returns 0 when the graph declares a dynamic anchor/class dimension, i.e.
  // "cannot be known before running". Used to reject a graph whose class count
  // contradicts the fixed class order a caller relies on.
  int numClasses() const { return num_classes_; }

  // Runs on the provided gray3 image and returns accepted boxes in ORIGINAL
  // coordinates. `conf_threshold` filters after the single inference pass.
  //
  // `error` is filled whenever the call cannot produce a trustworthy result
  // (input-shape mismatch, tensor-size mismatch, failed inference). Callers MUST
  // surface it: a silent empty vector would look like "no hands in this frame".
  std::vector<Box> detect(const cv::Mat &gray3, float conf_threshold, int out_w, int out_h,
                          std::string *error = nullptr);

  const std::vector<std::string> &classNames() const { return class_names_; }

  void release() { session_.release(); }

 private:
  // Verifies the tensor we are about to build matches the graph's declared input.
  bool validateInputAgainstModel(size_t tensor_elems, std::string *error) const;

  OrtSession session_;
  std::vector<std::string> class_names_;
  Config config_;
  int imgsz_ = 0;  // derived per model at load time
  int num_classes_ = 0;  // derived from the output shape, 0 when dynamic
};

// ---------------------------------------------------------------- BallTrack
// Official TrackNetV3 contract (verified against the official repo):
//   seq_len = 4, input 512x288, bg_mode = concat,
//   channels = [median(3), f(i-4)(3), f(i-3)(3), f(i-2)(3), f(i-1)(3)] = 15,
//   last_only = true -> a single output heatmap,
//   decode: threshold -> connected components -> largest bounds -> mean inside.
class BallTrack {
 public:
  bool load(const std::string &path, const Config &config, bool use_cuda,
            std::string *error);

  bool ok() const { return session_.ok(); }

  // Pushes one gray8 frame and returns the ball result for THAT frame.
  // Frames are buffered; before the window is full the result is kWarmup and no
  // inference is attempted (no frame is ever duplicated to fake history).
  BallResult push(const cv::Mat &gray8);

  // Median background of the buffered clip, in gray8. Cached incrementally.
  void reset();
  void setWindow(const cv::Mat &background, const std::vector<cv::Mat> &preceding);

  size_t buffered() const { return history_.size(); }
  size_t maxHistory() const { return max_history_; }
  int64_t framesSeen() const { return frames_seen_; }
  const cv::Mat &background() const { return median_gray_; }

  // Test/validation hook: the exact tensor the next inference would send.
  // Used by the synthetic 15-channel test and by the C++/Python input parity
  // check. Building it has no side effects on the temporal state.
  std::vector<float> buildInputForTest() const { return buildInput(); }
  // Window contents in order (oldest first) as the model would see them.
  std::vector<cv::Mat> historyForTest() const {
    return std::vector<cv::Mat>(history_.begin(), history_.end());
  }

  void release() { session_.release(); }

 private:
  std::vector<float> buildInput() const;
  // Folds one frame into the streaming per-pixel histogram and recomputes the
  // median background. Exact, bounded memory, no per-frame sort.
  void updateMedian(const cv::Mat &gray8);

  OrtSession session_;
  Config config_;
  std::deque<cv::Mat> history_;   // gray8 frames, most recent last
  cv::Mat median_gray_;           // background frame (see updateMedian comment)
  int64_t frames_seen_ = 0;
  size_t max_history_ = 0;
  bool explicit_window_ = false;
};

}  // namespace c_actual

#endif  // C_ACTUAL_INTERNAL_ONNX_HPP
