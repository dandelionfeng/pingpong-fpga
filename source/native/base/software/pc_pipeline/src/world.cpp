#include "pipeline/world.hpp"
#include "pipeline/stereo.hpp"
#include <cctype>
namespace pipeline {
static cv::Mat worldMatrix(const Json &j, int rows, int cols) {
  if (!j.is_array() || int(j.size()) != rows)
    throw std::runtime_error("world matrix rows mismatch");
  cv::Mat m(rows, cols, CV_64F);
  for (int y = 0; y < rows; ++y) {
    if (!j[y].is_array() || int(j[y].size()) != cols)
      throw std::runtime_error("world matrix columns mismatch");
    for (int x = 0; x < cols; ++x) {
      m.at<double>(y, x) = j[y][x].get<double>();
      if (!std::isfinite(m.at<double>(y, x)))
        throw std::runtime_error("nonfinite world matrix");
    }
  }
  return m;
}
static void rigid(const cv::Mat &m) {
  auto r = m(cv::Rect(0, 0, 3, 3));
  if (cv::norm(r * r.t() - cv::Mat::eye(3, 3, CV_64F)) > 1e-6 ||
      std::abs(cv::determinant(r) - 1) > 1e-6 ||
      cv::norm(m.row(3) - (cv::Mat_<double>(1, 4) << 0, 0, 0, 1)) > 1e-9)
    throw std::runtime_error("world transform is not a proper rigid transform");
}
TableWorldCalibration::TableWorldCalibration(const Path &index,
                                             const Path &cameraCalibration) {
  StereoCalibration checkedCamera(cameraCalibration);
  root_ = index.parent_path();
  auto hashes = Json::parse(readText(root_ / "SHA256SUMS.json"));
  auto checked = [&](const Path &rel) {
    auto path = root_ / rel;
    if (fileSha256(path) != hashes.at(pathUtf8(rel)).get<std::string>())
      throw std::runtime_error("world package checksum mismatch: " +
                               pathUtf8(rel));
    return Json::parse(readText(path));
  };
  auto j = checked(index.filename());
  if (j.at("schema") != "b-table-world-mapping-index-v1" || j.at("unit") != "m")
    throw std::runtime_error("unsupported table world index schema/unit");
  auto provenance = checked(utf8Path("evidence/input_manifest.json"));
  if (provenance.at("calibration_sha256") != checkedCamera.version())
    throw std::runtime_error("world mapping uses another camera calibration");
  auto camera = Json::parse(readText(cameraCalibration));
  cv::Mat lr = cv::Mat::eye(4, 4, CV_64F), rect = lr.clone();
  worldMatrix(camera.at("R_left_to_right"), 3, 3)
      .copyTo(lr(cv::Rect(0, 0, 3, 3)));
  for (int i = 0; i < 3; ++i)
    lr.at<double>(i, 3) = camera.at("T_m")[i];
  cv::Mat inverseR1 = worldMatrix(camera.at("R1"), 3, 3).t();
  inverseR1.copyTo(rect(cv::Rect(0, 0, 3, 3)));
  auto captures = j.at("captures");
  if (!captures.is_array() || captures.empty() || captures.size() > 64)
    throw std::runtime_error("invalid world capture list");
  for (const auto &item : captures) {
    auto capture = item.at("capture").get<std::string>();
    if (capture.size() != 18 || capture.substr(14) != ".bmp" ||
        !std::all_of(capture.begin(), capture.begin() + 14,
                     [](unsigned char c) { return std::isdigit(c); }))
      throw std::runtime_error("unsupported world capture filename");
    for (const auto &previous : poses_)
      if (previous.at("capture") == capture)
        throw std::runtime_error("duplicate world capture");
    auto rel = utf8Path("poses/table_world_" + capture.substr(0, 14) + ".json");
    auto p = checked(rel);
    if (p.at("schema") != "b-table-world-per-capture-v1" ||
        p.at("capture") != capture || p.at("unit") != "m")
      throw std::runtime_error("incompatible per-capture world pose");
    auto wc = worldMatrix(p.at("T_world_to_left_camera"), 4, 4);
    auto cw = worldMatrix(p.at("T_left_camera_to_world"), 4, 4);
    auto wr = worldMatrix(p.at("T_world_to_right_camera"), 4, 4);
    auto rw = worldMatrix(p.at("T_right_camera_to_world"), 4, 4);
    auto rectw = worldMatrix(p.at("T_rectified_left_to_world"), 4, 4);
    for (const auto &m : {wc, cw, wr, rw, rectw})
      rigid(m);
    if (cv::norm(wc * cw - cv::Mat::eye(4, 4, CV_64F)) > 1e-6 ||
        cv::norm(wr - lr * wc) > 1e-6 ||
        cv::norm(wr * rw - cv::Mat::eye(4, 4, CV_64F)) > 1e-6 ||
        cv::norm(rectw - cw * rect) > 1e-6 ||
        cv::norm(worldMatrix(p.at("Rcw"), 3, 3) - wc(cv::Rect(0, 0, 3, 3))) >
            1e-6)
      throw std::runtime_error(
          "inconsistent world/left/right/rectified transforms");
    for (int i = 0; i < 3; ++i)
      if (std::abs(p.at("tcw_m")[i].get<double>() - wc.at<double>(i, 3)) > 1e-6)
        throw std::runtime_error("inconsistent world translation");
    p["pose_sha256"] = fileSha256(root_ / rel);
    poses_.push_back(std::move(p));
    transforms_.push_back(cw);
  }
  metadata_ = {{"catalog_sha256", fileSha256(index)},
               {"camera_calibration_sha256", checkedCamera.version()},
               {"pose_count", poses_.size()},
               {"unit", "m"},
               {"index_active_world_mapping", j.at("active_world_mapping")},
               {"index_selected_capture", j.at("selected_capture")},
               {"validation_scope",
                "pose_numeric_consistency_not_independent_accuracy"}};
}
Path TableWorldCalibration::preview(size_t index) const {
  return root_ / "previews" /
         utf8Path("axes_" +
                  pose(index).at("capture").get<std::string>().substr(0, 14) +
                  ".jpg");
}
cv::Vec3d TableWorldCalibration::transformCameraPoint(size_t index,
                                                      cv::Vec3d point) const {
  for (auto v : point.val)
    if (!std::isfinite(v))
      throw std::runtime_error("nonfinite camera point");
  const auto &m = transforms_.at(index);
  cv::Vec3d result;
  for (int i = 0; i < 3; ++i)
    result[i] = m.at<double>(i, 0) * point[0] + m.at<double>(i, 1) * point[1] +
                m.at<double>(i, 2) * point[2] + m.at<double>(i, 3);
  return result;
}
Json TableWorldCalibration::describe(int index, const Json &binding,
                                     const std::string &inputHash) const {
  Json r = metadata_;
  r["world_transform_available"] = false;
  r["status"] = "invalid";
  r["coordinate_frame"] = "table_world";
  r["input_sha256"] = inputHash;
  r["reason"] = "pose_not_selected";
  if (index < 0)
    return r;
  const auto &p = pose(size_t(index));
  r["pose_capture"] = p.at("capture");
  r["pose_sha256"] = p.at("pose_sha256");
  r["world_origin"] = p.at("world_origin");
  r["axes"] = p.at("axes");
  r["metrics"] = p.at("metrics");
  r["world_frame_id"] = p.value("world_frame_id", "legacy_table_world");
  r["quality_status"] = p.value("quality_status", "accuracy_not_certified");
  r["usage"] = binding.is_object() ? binding.value("usage", "geometry_preview") : "geometry_preview";
  r["reason"] = "input_camera_pose_unmatched";
  if (p.value("quality_status", "") == "provisional_precision_pending" &&
      (!binding.is_object() || !binding.value("provisional_accuracy_accepted", false) ||
       binding.value("usage", "") != "visual_preview_only")) {
    r["reason"] = "provisional_pose_requires_preview_acceptance";
    return r;
  }
  if (binding.is_object() &&
      binding.value("schema", "") == "a-replay-world-binding-v1" &&
      binding.value("pose_capture", "") == p.at("capture") &&
      binding.value("pose_sha256", "") == p.at("pose_sha256") &&
      binding.value("camera_calibration_sha256", "") ==
          metadata_.at("camera_calibration_sha256") &&
      inputHash.size() == 64 &&
      binding.value("input_sha256", "") == inputHash &&
      binding.value("same_fixed_camera_mount", false) &&
      binding.value("board_placement_confirmed", false)) {
    r["status"] = "available";
    r["world_transform_available"] = true;
    r["reason"] = "explicit_input_pose_binding";
  }
  return r;
}
Json TableWorldCalibration::evaluate(int index, cv::Vec3d point,
                                     const Json &binding,
                                     const std::string &inputHash) const {
  auto r = describe(index, binding, inputHash);
  r["world_xyz_m"] = nullptr;
  r["height_above_table_m"] = nullptr;
  r["reference_world_xyz_m"] = nullptr;
  if (index < 0)
    return r;
  for (auto v : point.val)
    if (!std::isfinite(v)) {
      r["status"] = "invalid";
      r["reason"] = "nonfinite_camera_point";
      return r;
    }
  auto xyz = transformCameraPoint(size_t(index), point);
  if (!r.at("world_transform_available").get<bool>()) {
    r["reference_world_xyz_m"] = {xyz[0], xyz[1], xyz[2]};
    r["reference_status"] = "conditional_on_unmatched_pose_not_an_observation";
    return r;
  }
  r["status"] = "observed";
  r["world_xyz_m"] = {xyz[0], xyz[1], xyz[2]};
  r["height_above_table_m"] = xyz[2];
  return r;
}
Json TableWorldCalibration::mapMeasurement(int index, const Json &m,
                                         const Json &binding,
                                         const std::string &inputHash) const {
  if (m.value("coordinate_frame", "") != "left_camera" || m.value("unit", "") != "m")
    throw std::runtime_error("world preview requires left-camera meters");
  auto result = m;
  auto w = describe(index, binding, inputHash);
  w["pair_id"] = m.at("pair_id");
  w["timestamp_ns"] = m.at("timestamp_ns");
  const bool available = w.at("world_transform_available").get<bool>();
  if (available && m.at("measurement_calibration_sha256") != metadata_.at("camera_calibration_sha256"))
    throw std::runtime_error("world preview measurement camera hash mismatch");
  auto map = [&](const char *key) -> Json {
    if (!available || !m.contains(key) || m.at(key).is_null()) return nullptr;
    auto p = m.at(key).get<std::vector<double>>();
    if (p.size() != 3) throw std::runtime_error("world preview expects XYZ");
    auto v = transformCameraPoint(size_t(index), {p[0], p[1], p[2]});
    return {v[0], v[1], v[2]};
  };
  const auto state = m.value("track_state", m.value("status", "invalid"));
  w["status"] = available ? state : "invalid";
  // Keep observation, filter and prediction separate. Invalid rows never
  // retain stale coordinates; mapping does not change the source tracker.
  w["world_xyz_m"] = state == "observed" ? map("camera_xyz_m") : Json(nullptr);
  w["filtered_xyz_m"] = state == "invalid" ? Json(nullptr) : map("filtered_xyz_m");
  w["predicted_xyz_m"] = state == "predicted" ? map("predicted_xyz_m") : Json(nullptr);
  w["height_above_table_m"] = w["world_xyz_m"].is_null() ? Json(nullptr) : w["world_xyz_m"][2];
  w["predicted_height_above_table_m"] = w["predicted_xyz_m"].is_null() ? Json(nullptr) : w["predicted_xyz_m"][2];
  w["source_status"] = m.value("status", "invalid");
  w["pixel_evidence_verified"] = m.value("pixel_evidence_verified", false);
  w["event_evaluation_enabled"] = false;
  result["world_transform_available"] = available;
  result["world"] = std::move(w);
  return result;
}
} // namespace pipeline
