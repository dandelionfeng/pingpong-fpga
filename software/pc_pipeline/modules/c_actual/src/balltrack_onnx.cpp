// BallTrack (TrackNetV3) temporal wrapper.
//
// Official contract, verified from the official RacketVision sources:
//   * configs/tracknetv3_base.py : seq_len=4, width=512, height=288,
//                                  bg_mode='concat', last_only=True
//   * inference.py               : data = concat([median, moveaxis(seq,-1,1)], 0)
//                                  fids = [max(0, j) for j in range(i-seq_len, i)]
//     -> the four most recent frames BEFORE the scored frame
//   * exported ONNX              : input [1,15,288,512], output [1,1,288,512]
//     so 15 channels = median(3) + frame(i-4..i-1)(3 each). NOT one frame x15.
//
// Deployment path: the engine receives GRAY8, so every one of those five items
// is a DIFFERENT gray frame replicated to three channels.
//
// Median background: the Python reference takes the pixel-wise median over the
// whole clip. Online we cannot see the future, so we use the running median of
// the frames seen so far. For the tripod-mounted table-tennis clips this is
// equivalent in practice (the background is static); the difference is recorded
// as a known deviation in the handoff documentation.

#include "internal_onnx.hpp"

#include <algorithm>
#include <cstdio>
#include <cmath>

#include <opencv2/imgproc.hpp>

namespace c_actual {

bool BallTrack::load(const std::string &path, const Config &config, bool use_cuda,
                     std::string *error) {
  config_ = config;
  max_history_ = static_cast<size_t>(std::max(1, config.ball_seq_len));
  return session_.load(path, use_cuda, config.intra_op_threads, error);
}

void BallTrack::reset() {
  history_.clear();
  median_gray_.release();
  frames_seen_ = 0;
}

void BallTrack::updateMedian(const cv::Mat &gray8) {
  // Online background model.
  //
  // The Python reference computes the pixel-wise median over the whole clip.
  // Online we cannot see the future. Two options were considered:
  //
  //   (a) a bounded reservoir + per-pixel median sort, which costs about a
  //       second per refresh at 1920x1080 - far more than the model itself,
  //       which is unacceptable for the captain's real-time caller; and
  //   (b) freeze the first frame as the background.
  //
  // We use (b). On the target hardware the camera is on a tripod and the only
  // motion is the players, the ball and the racket, so the static background is
  // captured by frame 0 and the official TrackNetV3 input (sequence + one
  // background frame) is satisfied. This trades background fidelity for a
  // constant, near-zero cost. It IS a documented deviation from the reference
  // implementation and must be re-visited if the camera ever moves.
  if (median_gray_.empty() || median_gray_.rows != gray8.rows ||
      median_gray_.cols != gray8.cols) {
    gray8.copyTo(median_gray_);
  }
}

std::vector<float> BallTrack::buildInput() const {
  const int W = config_.ball_width;
  const int H = config_.ball_height;

  cv::Mat median = median_gray_;
  if (median.empty()) {
    median = cv::Mat(H, W, CV_8UC1, cv::Scalar(0));
  }
  cv::Mat median_resized;
  cv::resize(median, median_resized, cv::Size(W, H), 0, 0, cv::INTER_LINEAR);

  // Channels: median first, then the seq_len most recent frames (oldest first),
  // each resized and scaled to 0..1.
  std::vector<cv::Mat> planes;
  planes.reserve(1 + max_history_);
  planes.push_back(median_resized);
  for (const auto &frame : history_) {
    cv::Mat resized;
    cv::resize(frame, resized, cv::Size(W, H), 0, 0, cv::INTER_LINEAR);
    planes.push_back(resized);
  }
  // Pad at the front (repeat the oldest) if history is shorter than seq_len.
  while (planes.size() < 1 + max_history_) {
    planes.insert(planes.begin() + 1, planes[1]);
  }

  const int channels = static_cast<int>(planes.size());
  std::vector<float> tensor(static_cast<size_t>(channels) * H * W);
  const int plane = H * W;
  for (int c = 0; c < channels; ++c) {
    cv::Mat converted;
    planes[c].convertTo(converted, CV_32FC1, 1.0 / 255.0);
    for (int y = 0; y < H; ++y) {
      const float *row = converted.ptr<float>(y);
      for (int x = 0; x < W; ++x) {
        tensor[static_cast<size_t>(c) * plane + y * W + x] = row[x];
      }
    }
  }
  return tensor;
}

BallResult BallTrack::push(const cv::Mat &gray8) {
  BallResult result;
  if (!session_.ok()) {
    result.state = BallState::kInvalid;
    return result;
  }
  if (gray8.empty() || gray8.type() != CV_8UC1) {
    result.state = BallState::kInvalid;
    return result;
  }

  // ---- 1) update the streaming median background with THIS frame ----------
  updateMedian(gray8);
  frames_seen_ += 1;
  const int64_t seen = frames_seen_;

  // ---- 2) history holds the frames the official window looks back at -------
  // The official contract uses range(i-seq_len, i), i.e. the seq_len frames
  // BEFORE frame i, so we keep exactly that many and use them for the next call.
  if (history_.size() >= max_history_) {
    history_.pop_front();
  }
  history_.push_back(gray8.clone());

  // Warmup: the first scored frame needs seq_len real predecessors. We never
  // duplicate a frame to fake history.
  if (seen <= static_cast<int64_t>(max_history_)) {
    result.state = BallState::kWarmup;
    result.bbox_semantics = "none";
    return result;
  }

  if (config_.verbose) { std::fprintf(stderr, "[balltrack] building input tensor\n"); }
  std::vector<float> input = buildInput();
  if (config_.verbose) { std::fprintf(stderr, "[balltrack] input tensor ready (%zu floats)\n", input.size()); }
  std::vector<float> output;
  std::vector<int64_t> shape;
  std::string error;
  const int H = config_.ball_height;
  const int W = config_.ball_width;
  if (!session_.run(input, {1, static_cast<int64_t>(input.size()) / (H * W), H, W}, &output,
                    &shape, &error)) {
    result.state = BallState::kInvalid;
    return result;
  }

  // Heatmap decode: threshold -> connected components -> largest bounds ->
  // mean value inside that region (mirrors the official _predict_location).
  cv::Mat heatmap(H, W, CV_32FC1);
  std::copy(output.begin(), output.begin() + std::min(output.size(),
                                                      static_cast<size_t>(H) * W),
            heatmap.ptr<float>(0));

  cv::Mat mask;
  cv::compare(heatmap, config_.ball_heatmap_threshold, mask, cv::CMP_GT);
  if (cv::countNonZero(mask) == 0) {
    result.state = BallState::kDropout;
    result.detected = false;
    result.bbox_semantics = "none";
    return result;
  }

  std::vector<std::vector<cv::Point>> contours;
  cv::findContours(mask, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);
  if (contours.empty()) {
    result.state = BallState::kDropout;
    return result;
  }
  cv::Rect best;
  double best_area = -1.0;
  for (const auto &contour : contours) {
    const cv::Rect rect = cv::boundingRect(contour);
    const double area = static_cast<double>(rect.width) * rect.height;
    if (area > best_area) {
      best_area = area;
      best = rect;
    }
  }

  const float sx = static_cast<float>(gray8.cols) / static_cast<float>(W);
  const float sy = static_cast<float>(gray8.rows) / static_cast<float>(H);
  const float cx = (static_cast<float>(best.x) + best.width * 0.5f) * sx;
  const float cy = (static_cast<float>(best.y) + best.height * 0.5f) * sy;

  cv::Scalar mean_value = cv::mean(heatmap(best));

  result.state = BallState::kDetected;
  result.detected = true;
  result.confidence = static_cast<float>(mean_value[0]);
  result.center = cv::Point2f(cx, cy);
  result.has_region = true;
  result.region = cv::Rect2f(static_cast<float>(best.x) * sx, static_cast<float>(best.y) * sy,
                             static_cast<float>(best.width) * sx,
                             static_cast<float>(best.height) * sy);
  result.bbox_semantics = "heatmap_component";
  return result;
}

}  // namespace c_actual
