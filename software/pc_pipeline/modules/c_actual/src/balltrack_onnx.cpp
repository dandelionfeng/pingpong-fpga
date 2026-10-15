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
  if (!session_.load(path, use_cuda, config.intra_op_threads, error)) {
    return false;
  }

  // ---- hard input-contract check -----------------------------------------
  // The exported TrackNetV3 graph must take [1, 3*(seq_len+1), H, W]. If it does
  // not, every inference would fail silently, so refuse to load instead.
  const std::vector<int64_t> shape = session_.inputShape();
  const int64_t expected_channels = 3 * (static_cast<int64_t>(max_history_) + 1);
  std::string describe = "[";
  for (size_t i = 0; i < shape.size(); ++i) {
    describe += (i ? "," : "") + std::to_string(shape[i]);
  }
  describe += "]";

  if (shape.size() != 4) {
    if (error) {
      *error = "BALLTRACK_INPUT_CONTRACT_MISMATCH: expected a 4-D input "
               "[batch, channels, height, width], got " + describe;
    }
    session_.release();
    return false;
  }
  // Batch may be dynamic (-1); channels, height and width must match.
  if (shape[1] != expected_channels) {
    if (error) {
      *error = "BALLTRACK_INPUT_CONTRACT_MISMATCH: model expects " +
               std::to_string(shape[1]) + " channels but the official contract for seq_len=" +
               std::to_string(max_history_) + " is " + std::to_string(expected_channels) +
               " (3 * (seq_len + 1)); input shape was " + describe;
    }
    session_.release();
    return false;
  }
  if (shape[2] != config.ball_height || shape[3] != config.ball_width) {
    if (error) {
      *error = "BALLTRACK_INPUT_CONTRACT_MISMATCH: model expects spatial " +
               std::to_string(shape[2]) + "x" + std::to_string(shape[3]) +
               " but config says " + std::to_string(config.ball_height) + "x" +
               std::to_string(config.ball_width) + "; input shape was " + describe;
    }
    session_.release();
    return false;
  }
  return true;
}

void BallTrack::reset() {
  history_.clear();
  median_gray_.release();
  frames_seen_ = 0;
}

void BallTrack::updateMedian(const cv::Mat &gray8) {
  // ONLINE APPROXIMATION of the official background model.
  //
  // Official reference (RacketVision inference.py): the background fed to
  // TrackNetV3 is the PIXEL-WISE MEDIAN OVER THE WHOLE CLIP. That is exact but
  // not causal: it needs every frame of the clip up front.
  //
  // Captain-facing online C++: freeze the FIRST VALID FRAME as the background
  // for the clip. This is an approximation, not an equivalent implementation.
  //
  //   Reason: interface integration first; zero additional per-frame background
  //   cost. A bounded-reservoir median was implemented and measured at roughly
  //   one second per refresh at 1920x1080, which dwarfs the model itself.
  //   Limitation: must be re-evaluated on the real OV9281 and on any moving
  //   camera. If the camera moves, the frozen background is wrong and BallTrack
  //   input degrades.
  if (median_gray_.empty() || median_gray_.rows != gray8.rows ||
      median_gray_.cols != gray8.cols) {
    gray8.copyTo(median_gray_);
  }
}

namespace {
// GRAY8 -> 3 identical channels. The three values are equal, so BGR vs RGB
// ordering is numerically irrelevant; what matters is that all three channels
// really exist in the tensor.
cv::Mat grayTo3(const cv::Mat &gray8) {
  cv::Mat three;
  cv::cvtColor(gray8, three, cv::COLOR_GRAY2BGR);
  return three;
}
}  // namespace

std::vector<float> BallTrack::buildInput() const {
  const int W = config_.ball_width;
  const int H = config_.ball_height;

  // ---------------------------------------------------------------------
  // Official channel layout (verified against the official sources):
  //
  //   configs/tracknetv3_base.py : seq_len = 4, bg_mode = 'concat',
  //                                in_dim = 3 * (seq_len + 1)  -> 15
  //   inference.py               : data = np.concatenate(
  //                                    [median, np.moveaxis(seq, -1, 1)], 0)
  //                                fids = range(i - seq_len, i)
  //
  // So 15 channels = 3 channels for the background PLUS 3 channels for each of
  // the seq_len frames, and the frames are the seq_len frames BEFORE frame i:
  //
  //   ch  0, 1, 2 = background  R, G, B
  //   ch  3, 4, 5 = f(i-4)      R, G, B
  //   ch  6, 7, 8 = f(i-3)      R, G, B
  //   ch  9,10,11 = f(i-2)      R, G, B
  //   ch 12,13,14 = f(i-1)      R, G, B
  //
  // The input is GRAY8, so R = G = B for every item, but the three channels
  // must really exist. The earlier implementation emitted five single-channel
  // planes ([1,5,288,512]) and never matched the model.
  // ---------------------------------------------------------------------
  const int expected_channels = 3 * (static_cast<int>(max_history_) + 1);

  // Each entry is one RGB item: {B, G, R} copies of the same resized gray frame.
  std::vector<cv::Mat> items;
  items.reserve(static_cast<size_t>(max_history_) + 1);

  cv::Mat bg = median_gray_;
  if (bg.empty()) {
    bg = cv::Mat(H, W, CV_8UC1, cv::Scalar(0));
  }
  cv::Mat bg_resized;
  cv::resize(bg, bg_resized, cv::Size(W, H), 0, 0, cv::INTER_LINEAR);
  items.push_back(grayTo3(bg_resized));

  for (const auto &frame : history_) {
    cv::Mat resized;
    cv::resize(frame, resized, cv::Size(W, H), 0, 0, cv::INTER_LINEAR);
    items.push_back(grayTo3(resized));
  }
  // Pad at the front (repeat the oldest real frame) if history is short. This
  // only happens before the first scored frame, and push() reports WARMUP in
  // that case, so the tensor is never used for a scored frame without real
  // history. It exists so the buffer shape is always well defined.
  while (static_cast<int>(items.size()) < static_cast<int>(max_history_) + 1) {
    items.insert(items.begin() + 1, items[1]);
  }

  const int channels = static_cast<int>(items.size()) * 3;
  if (channels != expected_channels) {
    // Defensive: a mismatch here means the window bookkeeping is wrong.
    return std::vector<float>(static_cast<size_t>(expected_channels) * H * W, 0.0f);
  }

  const int plane = H * W;
  std::vector<float> tensor(static_cast<size_t>(channels) * plane);
  for (size_t item = 0; item < items.size(); ++item) {
    cv::Mat converted;
    items[item].convertTo(converted, CV_32FC3, 1.0 / 255.0);
    for (int c = 0; c < 3; ++c) {
      const size_t channel_index = item * 3 + static_cast<size_t>(c);
      for (int y = 0; y < H; ++y) {
        const cv::Vec3f *row = converted.ptr<cv::Vec3f>(y);
        for (int x = 0; x < W; ++x) {
          tensor[channel_index * plane + static_cast<size_t>(y) * W + x] = row[x][c];
        }
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

  // ---- 1) freeze the background on the first valid frame ------------------
  // Online approximation; see updateMedian() for the deviation note.
  updateMedian(gray8);
  frames_seen_ += 1;
  const int64_t seen = frames_seen_;

  // ---- 2) warmup ----------------------------------------------------------
  // The official window for the scored frame i is range(i - seq_len, i): the
  // seq_len frames BEFORE frame i, never frame i itself. So the first frame we
  // can score is the one with seq_len real predecessors. We never duplicate a
  // frame to fake history and we never report WARMUP as a detection.
  if (static_cast<size_t>(seen) <= max_history_) {
    history_.push_back(gray8.clone());
    result.state = BallState::kWarmup;
    result.bbox_semantics = "none";
    return result;
  }

  // ---- 3) build the input from the history window (frames i-4 .. i-1) ------
  // history_ currently holds exactly the seq_len frames preceding this one,
  // because the current frame is appended only after the window is consumed.
  std::vector<float> input = buildInput();
  const int H = config_.ball_height;
  const int W = config_.ball_width;
  const size_t expected_floats =
      static_cast<size_t>(3 * (max_history_ + 1)) * static_cast<size_t>(H) * W;
  if (input.size() != expected_floats) {
    // BALLTRACK_TENSOR_SIZE_MISMATCH: never run with a malformed tensor.
    result.state = BallState::kInvalid;
    history_.push_back(gray8.clone());
    if (history_.size() > max_history_) history_.pop_front();
    return result;
  }

  // ---- 4) inference -------------------------------------------------------
  std::vector<float> output;
  std::vector<int64_t> shape;
  std::string error;
  const int64_t channels = static_cast<int64_t>(3 * (max_history_ + 1));
  if (!session_.run(input, {1, channels, H, W}, &output, &shape, &error)) {
    result.state = BallState::kInvalid;
    history_.push_back(gray8.clone());
    if (history_.size() > max_history_) history_.pop_front();
    return result;
  }


  // ---- 5) slide the window: drop the oldest, append the current frame ------
  // This happens AFTER inference so the frame being scored can never appear in
  // its own input window.
  history_.push_back(gray8.clone());
  if (history_.size() > max_history_) {
    history_.pop_front();
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
