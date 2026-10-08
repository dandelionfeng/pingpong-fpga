#pragma once
#include <opencv2/core.hpp>
#include <cstdint>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace pingpong::ball {

enum class Eye { Left, Right };
enum class Polarity { Bright, Dark };
enum class MeasurementSource { Observed, Predicted, Filtered, Invalid };
enum class SearchSource { MotionMask, Prediction, DirectCandidate };
enum class QualityLevel { Clear, Reduced, Rejected };

// Draft in-process C++ interface; not a PCIe descriptor or frozen ABI.
struct FrameStamp {
    std::uint64_t pair_id = 0;
    Eye eye = Eye::Left;
    std::int64_t sample_time_ns = -1;
    std::string mode_id;
    std::string config_version;
    std::string calibration_version;
};
struct GrayFrame { cv::Mat gray; FrameStamp stamp; };
struct MotionFrame {
    cv::Mat mask;  // Decoded CV_8UC1, 0/1 or 0/255; byte order belongs upstream.
    FrameStamp stamp;
    bool valid = true;
    bool reference_valid = false;
    std::optional<std::uint64_t> reference_id;
    std::string failure_reason;
};
struct PredictionHint {
    FrameStamp target;  // Evaluated at this frame's sampling time.
    std::uint64_t source_pair_id = 0;
    std::int64_t source_sample_time_ns = -1;
    cv::Point2f image_center{};
    float previous_diameter_px = 0; // Zero means unavailable.
    std::string predictor_version;
};
struct Candidate {
    cv::Point2f search_center{};
    float area = 0;
    float score = 0;
    cv::Rect search_bounds{};
    float aspect_ratio = 1;
    float prediction_distance_px = 0;
};
struct Config {
    std::string config_version = "b-measure-v2-draft";
    int search_width = 640, search_height = 360;
    int image_width = 1280, image_height = 720;
    int roi_size = 256, local_size = 64;
    float search_to_image = 2;
    float min_area = 8, max_area = 1600; // Search components.
    int min_search_extent = 4, max_search_extent = 48;
    float max_search_aspect = 3;
    int max_candidates = 8;
    float min_ball_area = 50, max_ball_area = 1800;
    int min_ball_extent = 8, max_ball_extent = 44;
    float max_ball_aspect = 1.8f;
    float min_circularity = 0.60f;
    float min_dynamic_range = 12, min_contrast = 15;
    float max_foreground_fraction = 0.50f;
    float max_seed_distance_px = 24;
    float ambiguity_margin = 0.08f;
    float sobel_min = 30;
    float max_prediction_age_s = 0.25f;
};
struct Quality {
    QualityLevel level = QualityLevel::Rejected;
    double aspect_ratio = 0, contrast = 0, foreground_fraction = 0;
    double edge_coverage = 0, radial_asymmetry = 0, solidity = 0;
    bool touches_image_boundary = false, touches_roi_boundary = false;
    bool touches_local_boundary = false;
    bool possible_occlusion = false; // Shape warning, not semantic truth.
    std::vector<std::string> flags;
};
struct RoiPatch {
    cv::Mat gray;       // Always 256x256, replicate padding.
    cv::Mat valid_mask; // Actual source pixels are 255, padding is 0.
    cv::Rect requested; // Original-image coordinates, may have negative origin.
    cv::Rect image_valid; // Intersection in original-image coordinates.
    cv::Rect valid;       // Valid pixels in padded-ROI coordinates.
    std::string padding = "replicate";
};
struct Measurement {
    MeasurementSource source = MeasurementSource::Invalid;
    cv::Point2f image_center{std::numeric_limits<float>::quiet_NaN(), std::numeric_limits<float>::quiet_NaN()};
    cv::Point2f seed_image_center{};
    SearchSource search_source = SearchSource::DirectCandidate;
    FrameStamp stamp;
    bool identity_validated = false;
    bool reference_valid = false;
    std::optional<std::uint64_t> reference_id;
    cv::Rect requested_roi{};
    cv::Rect roi{};          // Valid rectangle in original-image coordinates.
    cv::Rect roi_valid{};    // Valid rectangle in padded-ROI coordinates.
    cv::Rect local_window{}; // 64x64, in padded-ROI coordinates.
    cv::Rect local_valid{};  // Valid rectangle in local-window coordinates.
    cv::Rect ball_bounds{};  // Selected component in original-image coordinates.
    std::string padding = "replicate";
    Polarity polarity = Polarity::Bright;
    double otsu_threshold = 0, area = 0, circularity = 0, edge_score = 0;
    double selection_score = 0;
    Quality quality;
    std::string reason;
    cv::Mat selected_mask; // 64x64 evidence, selected component only.
    cv::Mat local_gray;
};
struct EyeResult {
    FrameStamp stamp;
    MeasurementSource source = MeasurementSource::Invalid;
    std::string reason;
    std::optional<Measurement> observation;
    std::optional<PredictionHint> prediction; // Never merged with observation.
    std::vector<Candidate> candidates;
    std::vector<Measurement> attempts;
};
struct StereoResult {
    bool identity_validated = false;
    bool both_observed = false;
    std::string reason;
    EyeResult left, right;
};

cv::Point2f search_to_image(cv::Point2f p, const Config& cfg);
RoiPatch extract_roi(const cv::Mat& gray, cv::Point2f center, const Config& cfg);
std::vector<Candidate> connected_components_8u(const cv::Mat& mask, const Config& cfg,
    const std::optional<PredictionHint>& prediction = std::nullopt);
// Compatibility overload: pixel-only testing; identity_validated remains false.
Measurement measure_ball(const cv::Mat& gray, const Candidate& candidate, const Config& cfg);
// Formal entry validates image/mask identity before any pixel processing.
EyeResult measure_eye(const GrayFrame& frame, const MotionFrame& motion, const Config& cfg,
    const std::optional<PredictionHint>& prediction = std::nullopt);
StereoResult measure_pair(const GrayFrame& left, const GrayFrame& right,
    const MotionFrame& left_motion, const MotionFrame& right_motion, const Config& cfg,
    const std::optional<PredictionHint>& left_prediction = std::nullopt,
    const std::optional<PredictionHint>& right_prediction = std::nullopt);
const char* to_string(Eye value);
const char* to_string(MeasurementSource value);
const char* to_string(SearchSource value);
const char* to_string(QualityLevel value);

} // namespace pingpong::ball
