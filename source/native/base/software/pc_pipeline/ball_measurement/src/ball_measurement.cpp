#include "ball_measurement.hpp"
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <cmath>
#include <iterator>
#include <tuple>

namespace pingpong::ball {
namespace {
bool finite(cv::Point2f p) { return std::isfinite(p.x) && std::isfinite(p.y); }
bool valid_config(const Config& c) {
    return !c.config_version.empty() && c.search_width == 640 && c.search_height == 360 && c.image_width == 1280 &&
        c.image_height == 720 && c.roi_size == 256 && c.local_size == 64 && c.search_to_image == 2 &&
        c.max_candidates > 0 && c.max_candidates <= 8 && c.min_area > 0 && c.max_area >= c.min_area &&
        c.min_search_extent > 0 && c.max_search_extent >= c.min_search_extent && c.max_search_aspect >= 1 &&
        c.min_ball_area > 0 && c.max_ball_area >= c.min_ball_area && c.min_ball_extent > 0 &&
        c.max_ball_extent >= c.min_ball_extent && c.max_ball_aspect >= 1 &&
        c.min_circularity > 0 && c.min_circularity <= 1 && c.min_dynamic_range > 0 && c.min_contrast > 0 &&
        c.max_foreground_fraction > 0 && c.max_foreground_fraction < 1 &&
        c.max_seed_distance_px > 0 && c.max_seed_distance_px <= 32 && c.ambiguity_margin >= 0 &&
        c.sobel_min >= 0 && c.max_prediction_age_s > 0;
}
bool in_image(cv::Point2f p, const Config& c) {
    return finite(p) && p.x >= 0 && p.y >= 0 && p.x <= c.image_width - 1 && p.y <= c.image_height - 1;
}
cv::Rect centered(cv::Point2f p, int side) {
    return {static_cast<int>(std::floor(p.x - side * 0.5f)), static_cast<int>(std::floor(p.y - side * 0.5f)), side, side};
}
bool valid_stamp(const FrameStamp& s) {
    return (s.eye == Eye::Left || s.eye == Eye::Right) && s.sample_time_ns >= 0 &&
        !s.mode_id.empty() && !s.config_version.empty() && !s.calibration_version.empty();
}
std::string stamp_mismatch(const FrameStamp& a, const FrameStamp& b) {
    if (a.pair_id != b.pair_id) return "pair_id_mismatch";
    if (a.eye != b.eye) return "eye_mismatch";
    if (a.sample_time_ns != b.sample_time_ns) return "sample_time_mismatch";
    if (a.mode_id != b.mode_id) return "mode_mismatch";
    if (a.config_version != b.config_version) return "config_version_mismatch";
    if (a.calibration_version != b.calibration_version) return "calibration_version_mismatch";
    return {};
}
double quantile(const cv::Mat& image, const cv::Mat& valid, double fraction) {
    std::vector<unsigned char> values;
    for (int y = 0; y < image.rows; ++y) for (int x = 0; x < image.cols; ++x)
        if (valid.at<unsigned char>(y, x)) values.push_back(image.at<unsigned char>(y, x));
    if (values.empty()) return 0;
    const auto index = static_cast<std::size_t>(fraction * (values.size() - 1));
    std::nth_element(values.begin(), values.begin() + index, values.end());
    return values[index];
}
struct Component {
    cv::Mat mask;
    cv::Point2f center;
    cv::Rect bounds;
    Polarity polarity;
    double area = 0, circularity = 0, aspect = 0, contrast = 0, fraction = 0;
    double edge = 0, coverage = 0, radial = 0, solidity = 0, score = 0;
    bool image_boundary = false, local_boundary = false;
};
Measurement measure_seed(const cv::Mat& gray, cv::Point2f seed, float expected_diameter,
    SearchSource source, const Config& cfg) {
    Measurement out;
    out.seed_image_center = seed;
    out.search_source = source;
    if (!valid_config(cfg)) { out.reason = "invalid_config"; return out; }
    if (gray.empty() || gray.type() != CV_8UC1 || gray.size() != cv::Size(cfg.image_width, cfg.image_height)) {
        out.reason = "invalid_gray_image"; return out;
    }
    if (!in_image(seed, cfg)) { out.reason = "seed_outside_image"; return out; }
    const auto roi = extract_roi(gray, seed, cfg);
    out.requested_roi = roi.requested; out.roi = roi.image_valid; out.roi_valid = roi.valid;
    const cv::Point2f roi_seed(seed.x - roi.requested.x, seed.y - roi.requested.y);
    out.local_window = centered(roi_seed, cfg.local_size);
    out.local_valid = roi.valid & out.local_window;
    out.local_valid.x -= out.local_window.x; out.local_valid.y -= out.local_window.y;
    cv::Mat smoothed;
    cv::GaussianBlur(roi.gray, smoothed, cv::Size(3, 3), 0, 0, cv::BORDER_REPLICATE);
    const cv::Mat patch = smoothed(out.local_window);
    const cv::Mat valid = roi.valid_mask(out.local_window);
    out.local_gray = roi.gray(out.local_window).clone();
    const int valid_count = cv::countNonZero(valid);
    if (valid_count < 64) { out.reason = "insufficient_valid_pixels"; return out; }
    if (quantile(patch, valid, 0.99) - quantile(patch, valid, 0.01) < cfg.min_dynamic_range) {
        out.reason = "low_local_contrast"; return out;
    }
    // Exclude replicate padding from the Otsu histogram.
    cv::Mat samples(1, valid_count, CV_8U);
    int sample_index = 0;
    for (int y = 0; y < patch.rows; ++y) for (int x = 0; x < patch.cols; ++x)
        if (valid.at<unsigned char>(y, x)) samples.at<unsigned char>(0, sample_index++) = patch.at<unsigned char>(y, x);
    cv::Mat unused;
    out.otsu_threshold = cv::threshold(samples, unused, 0, 255, cv::THRESH_BINARY | cv::THRESH_OTSU);
    cv::Mat gx, gy, magnitude;
    cv::Sobel(patch, gx, CV_32F, 1, 0, 3, 1, 0, cv::BORDER_REPLICATE);
    cv::Sobel(patch, gy, CV_32F, 0, 1, 3, 1, 0, cv::BORDER_REPLICATE);
    cv::magnitude(gx, gy, magnitude);
    const cv::Point2f patch_seed(roi_seed.x - out.local_window.x, roi_seed.y - out.local_window.y);
    const int image_x = roi.requested.x + out.local_window.x, image_y = roi.requested.y + out.local_window.y;
    std::vector<Component> choices;
    for (const auto polarity : {Polarity::Bright, Polarity::Dark}) {
        cv::Mat binary;
        cv::threshold(patch, binary, out.otsu_threshold, 255,
            polarity == Polarity::Bright ? cv::THRESH_BINARY : cv::THRESH_BINARY_INV);
        cv::morphologyEx(binary, binary, cv::MORPH_CLOSE, cv::Mat::ones(3, 3, CV_8U),
            cv::Point(-1, -1), 1, cv::BORDER_REPLICATE);
        cv::bitwise_and(binary, valid, binary);
        cv::Mat labels, stats, centroids;
        const int count = cv::connectedComponentsWithStats(binary, labels, stats, centroids, 8, CV_32S);
        for (int label = 1; label < count; ++label) {
            Component c;
            c.polarity = polarity;
            c.area = stats.at<int>(label, cv::CC_STAT_AREA);
            c.bounds = {stats.at<int>(label, cv::CC_STAT_LEFT), stats.at<int>(label, cv::CC_STAT_TOP),
                stats.at<int>(label, cv::CC_STAT_WIDTH), stats.at<int>(label, cv::CC_STAT_HEIGHT)};
            c.aspect = static_cast<double>(std::max(c.bounds.width, c.bounds.height)) / std::min(c.bounds.width, c.bounds.height);
            c.fraction = c.area / valid_count;
            if (c.area < cfg.min_ball_area || c.area > cfg.max_ball_area ||
                std::min(c.bounds.width, c.bounds.height) < cfg.min_ball_extent ||
                std::max(c.bounds.width, c.bounds.height) > cfg.max_ball_extent || c.fraction > cfg.max_foreground_fraction) continue;
            cv::compare(labels, label, c.mask, cv::CMP_EQ);
            const auto moments = cv::moments(c.mask, true);
            c.center = {static_cast<float>(moments.m10 / moments.m00), static_cast<float>(moments.m01 / moments.m00)};
            const double distance = cv::norm(c.center - patch_seed);
            if (distance > cfg.max_seed_distance_px) continue;
            c.local_boundary = c.bounds.x == 0 || c.bounds.y == 0 || c.bounds.br().x == patch.cols || c.bounds.br().y == patch.rows;
            const cv::Rect image_bounds(image_x + c.bounds.x, image_y + c.bounds.y, c.bounds.width, c.bounds.height);
            c.image_boundary = image_bounds.x <= 0 || image_bounds.y <= 0 || image_bounds.br().x >= gray.cols || image_bounds.br().y >= gray.rows;
            std::vector<std::vector<cv::Point>> contours;
            cv::findContours(c.mask.clone(), contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_NONE);
            if (contours.empty()) continue;
            const auto contour = *std::max_element(contours.begin(), contours.end(), [](const auto& a, const auto& b) {
                return cv::contourArea(a) < cv::contourArea(b);
            });
            const double perimeter = cv::arcLength(contour, true);
            c.circularity = perimeter > 0 ? 4 * CV_PI * c.area / (perimeter * perimeter) : 0;
            std::vector<cv::Point> hull;
            cv::convexHull(contour, hull);
            const double hull_area = cv::contourArea(hull);
            c.solidity = hull_area > 0 ? cv::contourArea(contour) / hull_area : 0;
            cv::Mat surround, inverse;
            cv::dilate(c.mask, surround, cv::Mat::ones(9, 9, CV_8U));
            cv::bitwise_not(binary, inverse); // Other components do not count as background.
            cv::bitwise_and(surround, inverse, surround);
            cv::bitwise_and(surround, valid, surround);
            if (cv::countNonZero(surround) < 16) continue;
            const double signed_contrast = cv::mean(patch, c.mask)[0] - cv::mean(patch, surround)[0];
            c.contrast = polarity == Polarity::Bright ? signed_contrast : -signed_contrast;
            if (c.contrast < cfg.min_contrast) continue;
            double sum = 0, sum2 = 0, edge_sum = 0;
            bool bins[24] = {};
            for (const auto& p : contour) {
                const double dx = p.x - c.center.x, dy = p.y - c.center.y, radius = std::hypot(dx, dy);
                sum += radius; sum2 += radius * radius;
                const auto edge = magnitude.at<float>(p.y, p.x);
                edge_sum += edge;
                const int bin = std::min(23, static_cast<int>((std::atan2(dy, dx) + CV_PI) * 24 / (2 * CV_PI)));
                if (edge >= cfg.sobel_min) bins[bin] = true;
            }
            const double radius_mean = sum / contour.size();
            c.radial = radius_mean > 0 ? std::sqrt(std::max(0.0, sum2 / contour.size() - radius_mean * radius_mean)) / radius_mean : 1;
            c.edge = edge_sum / contour.size();
            c.coverage = std::count(std::begin(bins), std::end(bins), true) / 24.0;
            c.score = 0.55 * distance / cfg.max_seed_distance_px + 0.20 * std::max(0.0, 1 - c.circularity) +
                0.10 * (c.aspect - 1) + 0.05 * c.radial;
            if (expected_diameter > 0) c.score += 0.10 * std::abs(std::log(2 * std::sqrt(c.area / CV_PI) / expected_diameter));
            choices.push_back(std::move(c));
        }
    }
    if (choices.empty()) { out.reason = "no_ball_component"; return out; }
    std::sort(choices.begin(), choices.end(), [](const auto& a, const auto& b) { return a.score < b.score; });
    const auto acceptable = [&](const Component& c) { return !c.image_boundary && !c.local_boundary &&
        c.aspect <= cfg.max_ball_aspect && c.circularity >= cfg.min_circularity; };
    const auto chosen = std::find_if(choices.begin(), choices.end(), acceptable);
    const auto& c = chosen != choices.end() ? *chosen : choices.front();
    out.selected_mask = c.mask.clone();
    out.ball_bounds = {image_x + c.bounds.x, image_y + c.bounds.y, c.bounds.width, c.bounds.height};
    out.polarity = c.polarity; out.area = c.area; out.circularity = c.circularity;
    out.edge_score = c.edge; out.selection_score = c.score;
    auto& q = out.quality;
    q.aspect_ratio = c.aspect; q.contrast = c.contrast; q.foreground_fraction = c.fraction;
    q.edge_coverage = c.coverage; q.radial_asymmetry = c.radial; q.solidity = c.solidity;
    q.touches_image_boundary = c.image_boundary; q.touches_local_boundary = c.local_boundary;
    const cv::Rect roi_bounds(c.bounds.x + out.local_window.x, c.bounds.y + out.local_window.y, c.bounds.width, c.bounds.height);
    q.touches_roi_boundary = roi_bounds.x == 0 || roi_bounds.y == 0 || roi_bounds.br().x == cfg.roi_size || roi_bounds.br().y == cfg.roi_size;
    q.possible_occlusion = c.circularity < 0.85 || c.aspect > 1.15 || c.radial > 0.10 || c.solidity < 0.90;
    if (c.image_boundary) q.flags.push_back("image_boundary");
    if (c.local_boundary) q.flags.push_back("local_boundary");
    if (roi.valid.area() != cfg.roi_size * cfg.roi_size) q.flags.push_back("roi_padded");
    if (q.possible_occlusion) q.flags.push_back("possible_occlusion_or_shape_distortion");
    if (c.coverage < 0.75) q.flags.push_back("incomplete_edge_support");
    if (c.image_boundary) { out.reason = "image_boundary_truncation"; return out; }
    if (c.local_boundary) { out.reason = "local_boundary_truncation"; return out; }
    if (!acceptable(c)) { out.reason = "non_ball_shape"; return out; }
    const auto second = std::find_if(chosen + 1, choices.end(), acceptable);
    if (second != choices.end() && second->score - c.score < cfg.ambiguity_margin) {
        out.reason = "ambiguous_local_components"; q.flags.push_back("ambiguous"); return out;
    }
    if (c.coverage < 0.5) { out.reason = "insufficient_edge_support"; return out; }
    out.image_center = {image_x + c.center.x, image_y + c.center.y};
    out.source = MeasurementSource::Observed;
    q.level = q.possible_occlusion || c.coverage < 0.75 ? QualityLevel::Reduced : QualityLevel::Clear;
    out.reason = q.level == QualityLevel::Clear ? "ok" : "observed_reduced_quality";
    return out;
}
} // namespace

cv::Point2f search_to_image(cv::Point2f p, const Config& cfg) { return p * cfg.search_to_image + cv::Point2f(0.5f, 0.5f); }
RoiPatch extract_roi(const cv::Mat& gray, cv::Point2f center, const Config& cfg) {
    CV_Assert(valid_config(cfg) && gray.type() == CV_8UC1 && gray.size() == cv::Size(cfg.image_width, cfg.image_height) && in_image(center, cfg));
    RoiPatch out;
    out.requested = centered(center, cfg.roi_size);
    out.image_valid = out.requested & cv::Rect(0, 0, gray.cols, gray.rows);
    out.valid = {out.image_valid.x - out.requested.x, out.image_valid.y - out.requested.y, out.image_valid.width, out.image_valid.height};
    cv::copyMakeBorder(gray(out.image_valid), out.gray, out.valid.y, cfg.roi_size - out.valid.br().y,
        out.valid.x, cfg.roi_size - out.valid.br().x, cv::BORDER_REPLICATE | cv::BORDER_ISOLATED);
    out.valid_mask = cv::Mat::zeros(cfg.roi_size, cfg.roi_size, CV_8U);
    out.valid_mask(out.valid).setTo(255);
    return out;
}
std::vector<Candidate> connected_components_8u(const cv::Mat& mask, const Config& cfg, const std::optional<PredictionHint>& prediction) {
    CV_Assert(valid_config(cfg) && mask.type() == CV_8UC1 && mask.size() == cv::Size(cfg.search_width, cfg.search_height));
    cv::Mat binary, labels, stats, centroids;
    cv::compare(mask, 0, binary, cv::CMP_GT);
    const int count = cv::connectedComponentsWithStats(binary, labels, stats, centroids, 8, CV_32S);
    std::vector<Candidate> result;
    for (int i = 1; i < count; ++i) {
        Candidate c;
        c.area = static_cast<float>(stats.at<int>(i, cv::CC_STAT_AREA));
        c.search_bounds = {stats.at<int>(i, cv::CC_STAT_LEFT), stats.at<int>(i, cv::CC_STAT_TOP), stats.at<int>(i, cv::CC_STAT_WIDTH), stats.at<int>(i, cv::CC_STAT_HEIGHT)};
        c.aspect_ratio = static_cast<float>(std::max(c.search_bounds.width, c.search_bounds.height)) / std::min(c.search_bounds.width, c.search_bounds.height);
        if (c.area < cfg.min_area || c.area > cfg.max_area || std::min(c.search_bounds.width, c.search_bounds.height) < cfg.min_search_extent ||
            std::max(c.search_bounds.width, c.search_bounds.height) > cfg.max_search_extent || c.aspect_ratio > cfg.max_search_aspect) continue;
        c.search_center = {static_cast<float>(centroids.at<double>(i, 0)), static_cast<float>(centroids.at<double>(i, 1))};
        const float diameter = 2 * std::sqrt(c.area / static_cast<float>(CV_PI));
        const float size_cost = diameter < 6 ? 6 - diameter : diameter > 20 ? diameter - 20 : 0;
        c.score = -(c.aspect_ratio - 1 + size_cost / 20);
        if (prediction) { c.prediction_distance_px = static_cast<float>(cv::norm(search_to_image(c.search_center, cfg) - prediction->image_center)); c.score -= c.prediction_distance_px / cfg.local_size; }
        result.push_back(c);
    }
    std::sort(result.begin(), result.end(), [](const auto& a, const auto& b) {
        if (a.score != b.score) return a.score > b.score;
        return std::tie(a.search_center.y, a.search_center.x) < std::tie(b.search_center.y, b.search_center.x);
    });
    if (result.size() > static_cast<std::size_t>(cfg.max_candidates)) result.resize(cfg.max_candidates);
    return result;
}
Measurement measure_ball(const cv::Mat& gray, const Candidate& candidate, const Config& cfg) {
    return measure_seed(gray, search_to_image(candidate.search_center, cfg), candidate.area > 0 ?
        4 * std::sqrt(candidate.area / static_cast<float>(CV_PI)) : 0, SearchSource::DirectCandidate, cfg);
}
EyeResult measure_eye(const GrayFrame& frame, const MotionFrame& motion, const Config& cfg, const std::optional<PredictionHint>& prediction) {
    EyeResult result;
    result.stamp = frame.stamp;
    if (!valid_config(cfg)) { result.reason = "invalid_config"; return result; }
    if (!valid_stamp(frame.stamp) || !valid_stamp(motion.stamp)) { result.reason = "missing_frame_metadata"; return result; }
    result.reason = stamp_mismatch(frame.stamp, motion.stamp);
    if (!result.reason.empty()) return result;
    if (frame.stamp.config_version != cfg.config_version) { result.reason = "active_config_version_mismatch"; return result; }
    if (!motion.valid) { result.reason = "motion_failed"; return result; }
    if (motion.reference_valid && !motion.reference_id) { result.reason = "missing_reference_id"; return result; }
    if ((!motion.reference_valid && motion.reference_id) ||
        (motion.reference_id && *motion.reference_id >= frame.stamp.pair_id)) {
        result.reason = "invalid_reference_state"; return result;
    }
    if (frame.gray.type() != CV_8UC1 || frame.gray.size() != cv::Size(cfg.image_width, cfg.image_height)) { result.reason = "invalid_gray_image"; return result; }
    if (motion.mask.type() != CV_8UC1 || motion.mask.size() != cv::Size(cfg.search_width, cfg.search_height)) { result.reason = "invalid_motion_mask"; return result; }
    if (!motion.reference_valid && cv::countNonZero(motion.mask)) {
        result.reason = "uninitialized_motion_nonzero"; return result;
    }
    if (prediction) {
        if (!valid_stamp(prediction->target) || !stamp_mismatch(frame.stamp, prediction->target).empty()) { result.reason = "prediction_target_mismatch"; return result; }
        if (prediction->source_sample_time_ns < 0 || prediction->source_sample_time_ns >= frame.stamp.sample_time_ns) {
            result.reason = "invalid_or_stale_prediction"; return result;
        }
        const double age = (frame.stamp.sample_time_ns - prediction->source_sample_time_ns) * 1e-9;
        if (age > cfg.max_prediction_age_s || prediction->source_pair_id >= frame.stamp.pair_id ||
            prediction->predictor_version.empty() || !in_image(prediction->image_center, cfg) || !std::isfinite(prediction->previous_diameter_px) ||
            prediction->previous_diameter_px < 0 || prediction->previous_diameter_px > cfg.max_ball_extent) { result.reason = "invalid_or_stale_prediction"; return result; }
        result.prediction = prediction;
    }
    result.candidates = connected_components_8u(motion.mask, cfg, prediction);
    const auto append = [&](Measurement m) {
        m.stamp = frame.stamp; m.identity_validated = true; m.reference_id = motion.reference_id; m.reference_valid = motion.reference_valid;
        if (prediction && m.source == MeasurementSource::Observed &&
            cv::norm(m.image_center - prediction->image_center) > cfg.max_seed_distance_px) {
            m.source = MeasurementSource::Invalid;
            m.image_center = {std::numeric_limits<float>::quiet_NaN(), std::numeric_limits<float>::quiet_NaN()};
            m.quality.level = QualityLevel::Rejected;
            m.quality.flags.push_back("prediction_gate_rejection");
            m.reason = "outside_prediction_gate";
        }
        result.attempts.push_back(std::move(m));
    };
    for (const auto& c : result.candidates) {
        const float diameter = prediction && prediction->previous_diameter_px > 0 ? prediction->previous_diameter_px : 4 * std::sqrt(c.area / static_cast<float>(CV_PI));
        append(measure_seed(frame.gray, search_to_image(c.search_center, cfg), diameter, SearchSource::MotionMask, cfg));
    }
    if (prediction) append(measure_seed(frame.gray, prediction->image_center, prediction->previous_diameter_px, SearchSource::Prediction, cfg));
    std::vector<std::size_t> observed;
    for (std::size_t i = 0; i < result.attempts.size(); ++i) if (result.attempts[i].source == MeasurementSource::Observed) observed.push_back(i);
    const auto cost = [&](std::size_t i) {
        const auto& m = result.attempts[i];
        return m.selection_score + (prediction ? cv::norm(m.image_center - prediction->image_center) / cfg.max_seed_distance_px : 0);
    };
    std::sort(observed.begin(), observed.end(), [&](auto a, auto b) { return cost(a) < cost(b); });
    if (!observed.empty()) {
        const auto& best = result.attempts[observed.front()];
        for (std::size_t j = 1; j < observed.size(); ++j) {
            const auto& other = result.attempts[observed[j]];
            if (cv::norm(best.image_center - other.image_center) > 2 && cost(observed[j]) - cost(observed.front()) < cfg.ambiguity_margin) { result.reason = "ambiguous_frame_candidates"; return result; }
        }
        result.observation = best; result.source = MeasurementSource::Observed; result.reason = best.reason;
    } else if (prediction) { result.source = MeasurementSource::Predicted; result.reason = "prediction_only_no_observation"; }
    else result.reason = result.attempts.empty() ? "no_motion_candidates" : result.attempts.front().reason;
    return result;
}
StereoResult measure_pair(const GrayFrame& left, const GrayFrame& right,
    const MotionFrame& left_motion, const MotionFrame& right_motion, const Config& cfg,
    const std::optional<PredictionHint>& left_prediction, const std::optional<PredictionHint>& right_prediction) {
    StereoResult result;
    result.left.stamp = left.stamp; result.right.stamp = right.stamp;
    if (!valid_stamp(left.stamp) || !valid_stamp(right.stamp)) { result.reason = "missing_frame_metadata"; return result; }
    if (left.stamp.eye != Eye::Left || right.stamp.eye != Eye::Right) { result.reason = "stereo_eye_order_mismatch"; return result; }
    auto right_identity = right.stamp;
    right_identity.eye = left.stamp.eye;
    result.reason = stamp_mismatch(left.stamp, right_identity);
    if (!result.reason.empty()) { result.reason = "stereo_" + result.reason; return result; }
    // Validate both motion identities before processing either eye.
    if (!valid_stamp(left_motion.stamp) || !valid_stamp(right_motion.stamp)) { result.reason = "missing_frame_metadata"; return result; }
    result.reason = stamp_mismatch(left.stamp, left_motion.stamp);
    if (result.reason.empty()) result.reason = stamp_mismatch(right.stamp, right_motion.stamp);
    if (!result.reason.empty()) return result;
    result.identity_validated = true;
    result.left = measure_eye(left, left_motion, cfg, left_prediction);
    result.right = measure_eye(right, right_motion, cfg, right_prediction);
    result.both_observed = result.left.source == MeasurementSource::Observed && result.right.source == MeasurementSource::Observed;
    result.reason = result.both_observed ? "both_observed_geometry_pending" : "incomplete_pair_observation";
    return result;
}
const char* to_string(Eye v) { return v == Eye::Left ? "left" : "right"; }
const char* to_string(MeasurementSource v) {
    switch(v) { case MeasurementSource::Observed: return "observed"; case MeasurementSource::Predicted: return "predicted"; case MeasurementSource::Filtered: return "filtered"; default: return "invalid"; }
}
const char* to_string(SearchSource v) { switch(v) { case SearchSource::MotionMask: return "motion_mask"; case SearchSource::Prediction: return "prediction"; default: return "direct_candidate"; } }
const char* to_string(QualityLevel v) { switch(v) { case QualityLevel::Clear: return "clear"; case QualityLevel::Reduced: return "reduced"; default: return "rejected"; } }
} // namespace pingpong::ball
