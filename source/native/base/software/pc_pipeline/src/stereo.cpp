#include "pipeline/stereo.hpp"
#include <limits>
#include <opencv2/calib3d.hpp>
#include <opencv2/imgproc.hpp>
namespace pipeline {
static cv::Mat matrix(const Json &j, int rows, int cols) {
  if (!j.is_array() || int(j.size()) != rows)
    throw std::runtime_error("calibration rows mismatch");
  cv::Mat m(rows, cols, CV_64F);
  for (int y = 0; y < rows; ++y) {
    if (!j[y].is_array() || int(j[y].size()) != cols)
      throw std::runtime_error("calibration columns mismatch");
    for (int x = 0; x < cols; ++x) {
      m.at<double>(y, x) = j[y][x].get<double>();
      if (!std::isfinite(m.at<double>(y, x)))
        throw std::runtime_error("nonfinite calibration");
    }
  }
  return m;
}
StereoCalibration::StereoCalibration(const Path &file) {
  auto j = Json::parse(readText(file));
  if (j.at("schema") != "b-calibration-v1-draft" ||
      j.at("image_size_px") != Json::array({EyeWidth, EyeHeight}) ||
      j.at("left_right_order") != "stitched_left=physical_left_camera, "
                                  "stitched_right=physical_right_camera")
    throw std::runtime_error("unsupported calibration schema/size/eye order");
  if (j.at("square_size_m").get<double>() <= 0)
    throw std::runtime_error("metric scale required");
  rotation_ = matrix(j.at("R_left_to_right"), 3, 3);
  translation_ = matrix(Json::array({j.at("T_m")}), 1, 3).t();
  q_ = matrix(j.at("Q"), 4, 4);
  if (cv::norm(rotation_ * rotation_.t() - cv::Mat::eye(3, 3, CV_64F)) > 1e-5 ||
      std::abs(cv::determinant(rotation_) - 1) > 1e-5)
    throw std::runtime_error("invalid stereo rotation");
  double baseline = cv::norm(translation_);
  if (baseline < 0.001 || baseline > 1 ||
      std::abs(baseline - j.at("estimated_baseline_m").get<double>()) > 1e-6)
    throw std::runtime_error("invalid baseline");
  for (int e = 0; e < 2; ++e) {
    k_[e] = matrix(j.at(e ? "K_right" : "K_left"), 3, 3);
    auto d = j.at(e ? "D_right" : "D_left");
    d_[e] = matrix(Json::array({d}), 1, int(d.size()));
    r_[e] = matrix(j.at(e ? "R2" : "R1"), 3, 3);
    p_[e] = matrix(j.at(e ? "P2" : "P1"), 3, 4);
    if (k_[e].at<double>(0, 0) <= 0 || k_[e].at<double>(1, 1) <= 0 ||
        cv::norm(r_[e] * r_[e].t() - cv::Mat::eye(3, 3, CV_64F)) > 1e-5)
      throw std::runtime_error("invalid camera/rectification matrix");
    cv::initUndistortRectifyMap(k_[e], d_[e], r_[e], p_[e],
                                cv::Size(EyeWidth, EyeHeight), CV_32FC1,
                                mapx_[e], mapy_[e]);
  }
  cv::Mat rt = r_[1] * translation_;
  if (rt.at<double>(0) >= 0 || std::abs(rt.at<double>(1)) > 1e-5 ||
      std::abs(rt.at<double>(2)) > 1e-5 ||
      cv::norm(r_[1] * rotation_ - r_[0]) > 1e-5 ||
      std::abs(p_[1].at<double>(0, 3) / p_[1].at<double>(0, 0) + baseline) >
          1e-6 ||
      std::abs(q_.at<double>(3, 2) - 1 / baseline) > 1e-5)
    throw std::runtime_error("inconsistent R/T/rectification/P/Q");
  hash_ = fileSha256(file);
  cv::Mat expectedQ =
      (cv::Mat_<double>(4, 4) << 1, 0, 0, -p_[0].at<double>(0, 2), 0, 1, 0,
       -p_[0].at<double>(1, 2), 0, 0, 0, p_[0].at<double>(0, 0), 0, 0,
       1 / baseline,
       (p_[0].at<double>(0, 2) - p_[1].at<double>(0, 2)) / baseline);
  if (cv::norm(q_ - expectedQ) > 1e-5)
    throw std::runtime_error("Q is inconsistent with rectified projection");
  metadata_ = {
      {"calibration_sha256", hash_},
      {"coordinate_frame", "left_camera"},
      {"unit", "m"},
      {"baseline_m", baseline},
      {"world_transform_available", false},
      {"stereo_rms_px", j.at("stereo_rms_px")},
      {"validation_scope", "experimental_geometry_not_accuracy_certification"}};
}
Json StereoCalibration::triangulate(cv::Point2d left, cv::Point2d right,
                                    bool rectified) const {
  Json result = metadata_;
  result["status"] = "invalid";
  result["source"] = "manual_correspondence";
  for (auto pt : {left, right})
    if (!std::isfinite(pt.x) || !std::isfinite(pt.y) || pt.x < 0 || pt.y < 0 ||
        pt.x >= EyeWidth || pt.y >= EyeHeight) {
      result["reason"] = "point_out_of_image";
      return result;
    }
  std::vector<cv::Point2d> a{left}, b{right};
  if (!rectified) {
    cv::undistortPoints(a, a, k_[0], d_[0], r_[0], p_[0]);
    cv::undistortPoints(b, b, k_[1], d_[1], r_[1], p_[1]);
  }
  double disparity = a[0].x - b[0].x, dy = std::abs(a[0].y - b[0].y);
  result["rectified_points"] = {{a[0].x, a[0].y}, {b[0].x, b[0].y}};
  result["disparity_px"] = disparity;
  result["epipolar_error_px"] = dy;
  result["diagnostic_epipolar_limit_px"] = 3.0;
  if (disparity <= 0.5 || dy > 3) {
    result["reason"] = disparity <= 0.5 ? "nonpositive_or_tiny_disparity"
                                        : "epipolar_mismatch";
    return result;
  }
  cv::Mat h;
  cv::triangulatePoints(p_[0], p_[1], a, b, h);
  double w = h.at<double>(3, 0);
  if (std::abs(w) < 1e-12) {
    result["reason"] = "point_at_infinity";
    return result;
  }
  cv::Mat xr = h.rowRange(0, 3) / w, xc = r_[0].t() * xr,
          rightc = rotation_ * xc + translation_;
  if (!cv::checkRange(xc) || xc.at<double>(2) <= 0 ||
      rightc.at<double>(2) <= 0) {
    result["reason"] = "nonpositive_depth";
    return result;
  }
  result["status"] = "observed";
  result["camera_xyz_m"] = {xc.at<double>(0), xc.at<double>(1),
                            xc.at<double>(2)};
  result["depth_m"] = xc.at<double>(2);
  result["sensitivity_m_per_disparity_px"] =
      p_[0].at<double>(0, 0) * metadata_.at("baseline_m").get<double>() /
      (disparity * disparity);
  return result;
}
StereoView StereoCalibration::process(const FramePair &frame,
                                      bool dense) const {
  StereoView v;
  for (int e = 0; e < 2; ++e)
    cv::remap(frame.original[e], v.rectified[e], mapx_[e], mapy_[e],
              cv::INTER_LINEAR);
  v.summary = metadata_;
  v.summary["pair_id"] = frame.meta.pair_id;
  v.summary["timestamp_ns"] = frame.meta.timestamp_ns;
  if (!dense)
    return v;
  constexpr int disparities = 192, block = 5;
  auto matcher = [=](int min) {
    return cv::StereoSGBM::create(min, disparities, block, 8 * block * block,
                                  32 * block * block, 1, 31, 12, 100, 2,
                                  cv::StereoSGBM::MODE_SGBM_3WAY);
  };
  cv::Mat dl16, dr16, dl, dr, xyz;
  matcher(0)->compute(v.rectified[0], v.rectified[1], dl16);
  matcher(-disparities)->compute(v.rectified[1], v.rectified[0], dr16);
  dl16.convertTo(dl, CV_32F, 1. / 16);
  dr16.convertTo(dr, CV_32F, 1. / 16);
  cv::reprojectImageTo3D(dl, xyz, q_);
  v.depth_m = cv::Mat(EyeHeight, EyeWidth, CV_32F,
                      cv::Scalar(std::numeric_limits<float>::quiet_NaN()));
  v.valid = cv::Mat::zeros(EyeHeight, EyeWidth, CV_8U);
  cv::Mat intensity = cv::Mat::zeros(EyeHeight, EyeWidth, CV_8U);
  for (int y = 0; y < EyeHeight; ++y)
    for (int x = 0; x < EyeWidth; ++x) {
      float disparity = dl.at<float>(y, x);
      int rx = int(std::lround(x - disparity));
      if (disparity <= 0.5 || rx < 0 || rx >= EyeWidth)
        continue;
      float reverse = dr.at<float>(y, rx);
      if (reverse <= -disparities - 0.5 || std::abs(disparity + reverse) > 1.5)
        continue;
      auto pt = xyz.at<cv::Vec3f>(y, x);
      double z = r_[0].at<double>(0, 2) * pt[0] +
                 r_[0].at<double>(1, 2) * pt[1] +
                 r_[0].at<double>(2, 2) * pt[2];
      bool inside = true;
      for (int e = 0; e < 2; ++e) {
        int cx = e ? rx : x;
        if (mapx_[e].at<float>(y, cx) < 2 ||
            mapx_[e].at<float>(y, cx) >= EyeWidth - 2 ||
            mapy_[e].at<float>(y, cx) < 2 ||
            mapy_[e].at<float>(y, cx) >= EyeHeight - 2)
          inside = false;
      }
      if (!inside || !std::isfinite(z) || z < 0.3 || z > 10)
        continue;
      v.depth_m.at<float>(y, x) = float(z);
      v.valid.at<uint8_t>(y, x) = 255;
      intensity.at<uint8_t>(y, x) =
          cv::saturate_cast<uint8_t>(255 * (1 - (z - 0.3) / 9.7));
    }
  cv::applyColorMap(intensity, v.color, cv::COLORMAP_TURBO);
  v.color.setTo(cv::Scalar(0, 0, 0), v.valid == 0);
  v.summary["method"] = "SGBM_left_right_consistency";
  v.summary["valid_pixels"] = cv::countNonZero(v.valid);
  v.summary["valid_fraction"] =
      cv::countNonZero(v.valid) / double(EyeWidth * EyeHeight);
  v.summary["display_depth_range_m"] = {0.3, 10.0};
  v.summary["invalid_value"] = "NaN; black in preview";
  return v;
}
} // namespace pipeline
