#include <opencv2/core.hpp>
#include "c_perception_engine.hpp"
int main() {
  cv::Mat gray(1, 1, CV_8UC1, cv::Scalar(0));
  cv::Mat gray3 = c_actual::preprocess::grayToGray3(gray);
  return gray3.empty() ? 1 : 0;
}
