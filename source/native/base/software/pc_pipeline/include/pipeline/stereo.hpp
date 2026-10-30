#pragma once
#include "pipeline/pipeline.hpp"
namespace pipeline {
// Replay geometry in the left camera frame. No world transform or judgement.
struct StereoView {
  std::array<cv::Mat, 2> rectified;
  cv::Mat depth_m, valid, color;
  Json summary;
};
class StereoCalibration {
public:
  explicit StereoCalibration(const Path &file);
  StereoView process(const FramePair &frame, bool dense) const;
  Json triangulate(cv::Point2d left, cv::Point2d right,
                   bool rectified = false) const;
  const std::string &version() const { return hash_; }
  const Json &metadata() const { return metadata_; }

private:
  std::array<cv::Mat, 2> k_, d_, r_, p_, mapx_, mapy_;
  cv::Mat rotation_, translation_, q_;
  Json metadata_;
  std::string hash_;
};
Json importStereoAvi(const Path &video, const Path &manifest);
} // namespace pipeline
