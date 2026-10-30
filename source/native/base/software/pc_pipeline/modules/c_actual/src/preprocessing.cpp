#include "c_perception_engine.hpp"

#include <opencv2/imgproc.hpp>

#include <stdexcept>

namespace c_actual {
namespace preprocess {

cv::Mat grayToGray3(const cv::Mat &gray) {
  if (gray.empty()) {
    throw std::invalid_argument("grayToGray3: empty image");
  }
  if (gray.type() != CV_8UC1) {
    throw std::invalid_argument(
        "grayToGray3: input must be CV_8UC1 (single-channel uint8 grayscale)");
  }
  cv::Mat three;
  // The three channels are identical, so BGR vs RGB is numerically irrelevant
  // here; we use the OpenCV-documented conversion for clarity.
  cv::cvtColor(gray, three, cv::COLOR_GRAY2BGR);
  return three;
}

cv::Mat letterbox(const cv::Mat &bgr, int size, float *scale_out, int *pad_x_out,
                  int *pad_y_out) {
  if (bgr.empty()) {
    throw std::invalid_argument("letterbox: empty image");
  }
  const int w = bgr.cols;
  const int h = bgr.rows;
  const float scale = std::min(static_cast<float>(size) / static_cast<float>(w),
                               static_cast<float>(size) / static_cast<float>(h));
  const int new_w = static_cast<int>(std::round(w * scale));
  const int new_h = static_cast<int>(std::round(h * scale));

  cv::Mat resized;
  cv::resize(bgr, resized, cv::Size(new_w, new_h), 0, 0, cv::INTER_LINEAR);

  cv::Mat canvas(size, size, CV_8UC3, cv::Scalar(114, 114, 114));
  const int pad_x = (size - new_w) / 2;
  const int pad_y = (size - new_h) / 2;
  resized.copyTo(canvas(cv::Rect(pad_x, pad_y, new_w, new_h)));

  if (scale_out) *scale_out = scale;
  if (pad_x_out) *pad_x_out = pad_x;
  if (pad_y_out) *pad_y_out = pad_y;
  return canvas;
}

}  // namespace preprocess
}  // namespace c_actual
