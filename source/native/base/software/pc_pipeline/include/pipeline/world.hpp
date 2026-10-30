#pragma once
#include "pipeline/pipeline.hpp"
namespace pipeline {
// Optional table mapping. A numerical pose alone does not identify an input.
class TableWorldCalibration {
public:
  TableWorldCalibration(const Path &index, const Path &cameraCalibration);
  size_t size() const { return poses_.size(); }
  const Json &pose(size_t index) const { return poses_.at(index); }
  const Json &metadata() const { return metadata_; }
  Path preview(size_t index) const;
  cv::Vec3d transformCameraPoint(size_t index, cv::Vec3d point) const;
  Json describe(int index, const Json &binding,
                const std::string &inputHash) const;
  Json evaluate(int index, cv::Vec3d point, const Json &binding,
                const std::string &inputHash) const;
  Json mapMeasurement(int index, const Json &measurement, const Json &binding,
                      const std::string &inputHash) const;

private:
  Path root_;
  std::vector<Json> poses_;
  std::vector<cv::Mat> transforms_;
  Json metadata_;
};
} // namespace pipeline
