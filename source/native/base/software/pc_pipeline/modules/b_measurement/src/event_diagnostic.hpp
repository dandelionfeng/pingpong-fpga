#pragma once
#include "mask_release.hpp"
#include <set>
// Same-frame semantic boxes and actual stereo observations only. Predictions
// never enter event fitting; this helper does not assign truth labels.
namespace pipeline {
class DiagnosticEvents {
  using Tr = pingpong::trajectory::EventFrame;
  using Observation = pingpong::trajectory::WorldObservation;
  using Stamp = pingpong::ball::FrameStamp;
public:
  bool relaxed=false,realtime=false;
  void clear() { frames_.clear(); detections_.clear(); releasePixels_.clear(); }
  void update(Json &out,const FramePair &f,const std::vector<DetectionResult> &records,
              const std::optional<Observation> &observation,const std::string &calibrationHash,const MotionResult *motion=nullptr) {
    namespace tr=pingpong::trajectory;
    if(!out.value("world_transform_available",false)) return;
    Stamp stamp{f.meta.pair_id,pingpong::ball::Eye::Left,f.meta.timestamp_ns,
                "original_eye_1280x720",f.meta.config_version,calibrationHash};
    const bool maskEnabled=std::getenv("PIPELINE_MASK_RELEASE") && std::string(std::getenv("PIPELINE_MASK_RELEASE"))=="1";
    const auto pixelStart=Clock::now();
    if(maskEnabled && motion)releasePixels_.observe(f,*motion,records,observation,calibrationHash);
    double maskOnlyMs=std::chrono::duration<double,std::milli>(Clock::now()-pixelStart).count();
    if(observation && out.value("semantic_ball_supported",false)) {
      Tr item; item.stamp=stamp; item.observed=observation->world;
      item.left_ball=observation->left; item.right_ball=observation->right;
      // Weight is numerical pixel covariance, not an accepted metric error bar.
      const double variance=std::max({1e-6,observation->covariance(0,0),observation->covariance(1,1),observation->covariance(2,2)});
      item.weight=1/variance; item.fit_eligible=true;
      frames_.erase(std::remove_if(frames_.begin(),frames_.end(),[&](const auto &x){return x.stamp.pair_id==stamp.pair_id;}),frames_.end());
      frames_.push_back(item);
      std::sort(frames_.begin(),frames_.end(),[](const auto&a,const auto&b){return a.stamp.sample_time_ns<b.stamp.sample_time_ns;});
      for(const auto &r:records) if(r.status=="ok" && r.meta.pair_id==f.meta.pair_id &&
                                  r.meta.timestamp_ns==f.meta.timestamp_ns) {
        detections_.erase(std::remove_if(detections_.begin(),detections_.end(),[&](const auto &d){return d.source.pair_id==stamp.pair_id && int(d.source.eye)==int(r.eye);}),detections_.end());
        for(const auto &box:r.boxes) {
          auto label=box.value("class",std::string());
          if(label!="hand" && label!="racket") continue;
          const auto b=box.at("bbox").get<std::vector<double>>();
          if(b.size()!=4) continue;
          tr::SemanticDetection d; d.source=stamp; d.source.eye=static_cast<pingpong::ball::Eye>(r.eye);
          // Offline detector results are source-aligned. Real completion timing
          // remains in A/C logs and is not evaluated as live latency here.
          const double ageMs=realtime?r.diagnostics.value("source_age_ms",100000.0):0;
          if(!std::isfinite(ageMs)||ageMs<0)continue;
          d.completed_time_ns=stamp.sample_time_ns+int64_t(std::llround(ageMs*1e6));
          d.model_version=r.meta.model_version; d.label=label; d.score=box.value("confidence",0.0);
          d.box={b[0],b[1],b[2],b[3]}; detections_.push_back(d);
        }
      }
    }
    std::sort(detections_.begin(),detections_.end(),[](const auto&a,const auto&b){return a.source.sample_time_ns<b.source.sample_time_ns;});
    while(frames_.size()>512) frames_.erase(frames_.begin());
    if(!frames_.empty()) while(!detections_.empty() && detections_.front().source.pair_id<frames_.front().stamp.pair_id) detections_.erase(detections_.begin());
    tr::EventConfig cfg; cfg.diagnostic_relaxed=relaxed;
    if(relaxed) cfg.min_score=.10;
    auto result=tr::analyze_events(frames_,detections_,cfg);
    const auto legacyRelease=result.release;
    std::string releaseEstimator="legacy_bbox";
    auto maskEstimate=[&](){const auto t=Clock::now();auto p=releasePixels_.estimate(*legacyRelease);
      maskOnlyMs+=std::chrono::duration<double,std::milli>(Clock::now()-t).count();return p;};
    if(maskEnabled && legacyRelease)if(auto proposal=maskEstimate()) {
      bool usable=true;
      if(result.fit.valid) {
        std::set<uint64_t> ids(result.fit.used_pair_ids.begin(),result.fit.used_pair_ids.end());
        std::vector<tr::FitSample> samples;
        for(const auto &row:frames_)if(row.observed && ids.count(row.stamp.pair_id))
          samples.push_back({row.stamp.pair_id,row.stamp.sample_time_ns,*row.observed,row.weight,true});
        auto revised=tr::fit_flight(samples,proposal->interval,std::nullopt,0,relaxed);
        usable=revised.valid;if(usable)result.fit=std::move(revised);
      }
      if(usable){result.release=proposal->interval;releaseEstimator="mask_gray_distance_changepoint";}
    }
    const double pixelMs=std::chrono::duration<double,std::milli>(Clock::now()-pixelStart).count();
    Json e={{"status",result.status},{"reason",result.reason},{"fit_valid",result.fit.valid},
            {"semantic_associated",result.associated_detections},{"semantic_ignored",result.ignored_detections},
            {"actual_stereo_frames",frames_.size()},{"height_m",nullptr},{"chord_angle_from_vertical_deg",nullptr},
            {"launch_velocity_angle_from_vertical_deg",nullptr},{"predictions_used_for_fit",false},
            {"accuracy_validated",false},{"semantic_latency_policy",realtime?"age_since_original_frame_retention":"offline_source_aligned"},{"measurement_calibration_sha256",calibrationHash}};
    for(auto pair:{std::make_pair("release",result.release),std::make_pair("apex",result.apex),std::make_pair("contact",result.contact)})
      if(pair.second) e[pair.first]={{"begin_ns",pair.second->begin_ns},{"end_ns",pair.second->end_ns}};
    e["fit_reason"]=result.fit.reason;
    e["release_estimator"]=releaseEstimator;
    if(maskEnabled) {
      e["release_pixel_evidence"]=releasePixels_.diagnostics();
      e["mask_release_update_ms"]=pixelMs;
      e["mask_release_only_ms"]=maskOnlyMs;
      e["release_world_source"]=releaseEstimator=="legacy_bbox"?"legacy_flight_fit":"flight_fit_at_midpoint_of_pixel_separation_interval";
      if(legacyRelease)e["legacy_release"]={{"begin_ns",legacyRelease->begin_ns},{"end_ns",legacyRelease->end_ns}};
    }
    if(result.fit.valid) {
      const auto &fit=result.fit;
      e["height_m"]=fit.height_m;
      e["chord_angle_from_vertical_deg"]=fit.chord_angle_deg;
      e["launch_velocity_angle_from_vertical_deg"]=fit.velocity_angle_deg;
      e["fit_residual_rms_m"]=fit.residual_rms_m;
      e["used_pair_ids"]=fit.used_pair_ids;
      e["fit_origin_ns"]=fit.origin_ns; e["release_offset_s"]=fit.release_offset_s; e["apex_s"]=fit.apex_s;
      e["x_coefficients"]={fit.x[0],fit.x[1]}; e["y_coefficients"]={fit.y[0],fit.y[1]};
      e["z_coefficients"]={fit.z[0],fit.z[1],fit.z[2]};
      e["release_world_m"]={fit.release_world[0],fit.release_world[1],fit.release_world[2]};
      e["apex_world_m"]={fit.apex_world[0],fit.apex_world[1],fit.apex_world[2]};
    }
    out["events"]=std::move(e);
  }
private:
  MaskRelease releasePixels_;
  std::vector<Tr> frames_;
  std::vector<pingpong::trajectory::SemanticDetection> detections_;
};
} // namespace pipeline
