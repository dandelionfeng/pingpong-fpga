#pragma once
#include "ball_measurement.hpp"
#include <opencv2/calib3d.hpp>
#include <optional>
#include <string>
#include <vector>

namespace pingpong::trajectory {
using ball::FrameStamp;
using ball::Eye;
struct Calibration {
    cv::Mat K1, D1, K2, D2, R, T, R1, R2, P1, P2, Rcw, tcw;
    cv::Size size{1280,720};
    std::string version, unit="m", provenance;
    bool world_valid=false;
    double mono_rms_left=0, mono_rms_right=0, stereo_rms=0;
};
bool validate_calibration(const Calibration&, std::string& reason);
void rectify(Calibration&);
void save_calibration(const Calibration&, const std::string& path);
Calibration load_calibration(const std::string& path);
Calibration calibrate_chessboards(const std::vector<cv::Mat>& left,
    const std::vector<cv::Mat>& right, cv::Size corners, double square_size,
    const std::string& unit, const std::string& version);
bool set_world_pose(Calibration&, const std::vector<cv::Point3d>& world,
    const std::vector<cv::Point2d>& left_pixels, std::string& reason);
// Preview only: also permits square-unit practice calibration, without world pose.
bool rectify_images(const Calibration&, const cv::Mat&, const cv::Mat&,
    cv::Mat& left, cv::Mat& right, std::string& reason);

struct PixelObservation {
    FrameStamp stamp;
    cv::Point2d center;
    double diameter_px=0, sigma_px=0.3;
    bool observed=true, reduced=false, identity_validated=true;
};
std::optional<PixelObservation> from_measurement(const ball::EyeResult&);
// Preserve the individually validated attempts so stereo geometry can resolve
// a single-eye ambiguity. Never turn a predicted/invalid attempt into a point.
std::vector<PixelObservation> observation_candidates(const ball::EyeResult&);
struct GeometryConfig {
    double epipolar_px=2, reprojection_px=2, min_disparity_px=0.5;
    double min_depth_m=0.1, max_depth_m=15, max_diameter_ratio=2;
    // Optional caller-declared error budget, not estimated camera accuracy.
    double calibration_position_sigma_m=0, world_translation_sigma_m=0;
    double world_rotation_sigma_rad=0, sync_sigma_s=0, sync_speed_bound_m_s=15;
};
struct WorldObservation {
    FrameStamp stamp;
    bool valid=false;
    cv::Vec3d world{}, camera{};
    cv::Matx33d covariance=cv::Matx33d::eye()*1e-4;
    cv::Point2d left{}, right{};
    double epipolar_error_px=0, reprojection_error_px=0, disparity_px=0;
    bool reduced=false;
    std::string reason;
    std::string uncertainty_scope="pixel_noise_only";
};
WorldObservation triangulate(const PixelObservation&, const PixelObservation&,
    const Calibration&, const GeometryConfig& cfg={});
struct StereoMatch {
    bool valid=false;
    std::string reason;
    std::size_t left_index=0, right_index=0;
    WorldObservation observation;
};
// Geometry/size/prediction hypothesis only; a round distractor on the same
// epipolar line still needs C identity evidence. Equally plausible pairs reject.
StereoMatch match_stereo(const std::vector<PixelObservation>& left,
    const std::vector<PixelObservation>& right,const Calibration&,
    const std::optional<cv::Vec3d>& predicted=std::nullopt,
    const GeometryConfig& cfg={});
std::optional<cv::Point2d> project(const cv::Vec3d& world, Eye, const Calibration&);

struct TrackConfig {
    double gravity=9.80665, max_gap_s=0.25, gate_squared=16.27;
    double acceleration_noise=4, initial_velocity_variance=25;
};
struct TrackResult {
    FrameStamp stamp;
    std::optional<cv::Vec3d> raw_observed, filtered, predicted, velocity;
    bool accepted=false, reset=false;
    double dt=0, innovation_squared=0;
    std::string reason;
};
class Tracker {
public:
    explicit Tracker(TrackConfig cfg={}) : cfg_(cfg) {}
    TrackResult update(const FrameStamp&, const std::optional<WorldObservation>&, bool free_flight);
    std::optional<cv::Vec3d> predict(const FrameStamp&, bool free_flight) const;
    std::optional<ball::PredictionHint> roi_hint(const FrameStamp&, Eye,
        const Calibration&, bool free_flight, float diameter_px=0) const;
    void clear();
    // Caller must first confirm a contact from actual observations/semantics.
    bool reset_after_contact(const WorldObservation& previous,
        const WorldObservation& current, bool free_flight, std::string& reason);
private:
    TrackConfig cfg_;
    bool initialized_=false;
    FrameStamp last_, last_observed_;
    cv::Mat state_, covariance_;
    cv::Vec3d last_observed_position_{};
    bool last_flight_=false;
    int rejected_streak_=0;
    std::optional<cv::Vec3d> last_rejected_position_;
    std::int64_t last_rejected_time_=0;
};

struct FitSample {
    std::uint64_t pair_id=0;
    std::int64_t time_ns=0;
    cv::Vec3d world{};
    double weight=1;
    bool observed=true;
};
struct TimeInterval { std::int64_t begin_ns=0, end_ns=0; };
struct FlightFit {
    bool valid=false;
    std::string reason;
    std::int64_t origin_ns=0;
    cv::Vec2d x{}, y{};
    cv::Vec3d z{};
    double apex_s=0, release_offset_s=0, residual_rms_m=0, height_m=0, height_low_m=0, height_high_m=0;
    bool release_refined=false;
    double measurement_sigma_m=0;
    std::string release_method="interval_midpoint";
    double chord_angle_deg=0, velocity_angle_deg=0;
    cv::Vec3d release_world{}, apex_world{};
    std::vector<std::uint64_t> used_pair_ids;
};
FlightFit fit_flight(const std::vector<FitSample>&, TimeInterval release,
    const std::optional<cv::Vec3d>& last_held_position=std::nullopt,
    double held_sigma_m=0);

struct SemanticDetection {
    FrameStamp source;
    std::int64_t completed_time_ns=0;
    std::string label, model_version;
    cv::Rect2d box;
    double score=0;
    bool visible=true;
};
struct EventFrame {
    FrameStamp stamp;
    std::optional<cv::Vec3d> observed;
    std::optional<cv::Point2d> left_ball, right_ball;
    double weight=1;
    bool fit_eligible=true; // Keep raw geometry for contact evidence; exclude
                            // Kalman-gated outliers from free-flight fitting.
};
struct EventConfig {
    double min_score=0.25, near_px=18, rise_m_s=0.25, contact_velocity_change=1.2;
    double max_observation_gap_s=0.08, max_detection_latency_s=0.25;
};
struct EventResult {
    std::string status="unknown", reason;
    std::optional<TimeInterval> release, apex, contact;
    FlightFit fit;
    std::vector<std::string> states;
    int associated_detections=0, ignored_detections=0;
};
// Offline helper, also used on the bounded active window by OnlineEvents.
EventResult analyze_events(const std::vector<EventFrame>&,
    const std::vector<SemanticDetection>&, const EventConfig& cfg={});

struct OnlineConfig {
    std::size_t max_frames=256, max_detections=2048, max_pending_detections=32;
    double max_event_s=4, settle_s=0.30;
    int restart_holding_frames=3;
};
struct EventUpdate {
    std::uint64_t event_id=0, revision=0;
    std::int64_t published_time_ns=0;
    bool finalized=false;
    std::string trigger;
    EventResult result;
    std::vector<EventFrame> frames; // Bounded evidence snapshot; take_updates drains.
};
struct OnlineStats {
    std::size_t rejected_detections=0, duplicate_detections=0, expired_detections=0;
    std::size_t queue_overflows=0, resets=0, peak_frames=0, peak_detections=0;
};
class OnlineEvents {
public:
    explicit OnlineEvents(EventConfig event={}, OnlineConfig online={});
    bool push_frame(const EventFrame&, std::int64_t now_ns, std::string& reason);
    bool push_detection(const SemanticDetection&, std::int64_t arrival_ns, std::string& reason);
    void advance(std::int64_t now_ns);
    void finish(std::int64_t now_ns);
    std::vector<EventUpdate> take_updates();
    const EventResult& current() const { return current_; }
    const OnlineStats& stats() const { return stats_; }
    std::size_t buffered_frames() const { return frames_.size(); }
    std::size_t buffered_detections() const { return detections_.size()+pending_.size(); }
private:
    void recompute(std::int64_t now, const std::string& trigger, bool final=false);
    void close(std::int64_t now, const std::string& trigger);
    bool holding(const EventFrame&) const;
    EventConfig cfg_;
    OnlineConfig online_;
    std::vector<EventFrame> frames_;
    std::vector<SemanticDetection> detections_,pending_;
    std::vector<EventUpdate> updates_;
    EventResult current_;
    OnlineStats stats_;
    std::uint64_t event_id_=1, revision_=0;
    std::int64_t now_=0;
    std::string signature_;
};
} // namespace pingpong::trajectory
