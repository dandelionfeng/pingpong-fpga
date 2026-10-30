#include "pipeline/pipeline.hpp"
#include "trajectory.hpp"
#include <cstdlib>
#include "event_diagnostic.hpp"

namespace pipeline {
namespace {
namespace ball = pingpong::ball;
namespace tr = pingpong::trajectory;
cv::Mat matrix(const Json &j, int rows, int cols) {
  std::vector<double> values;
  for (auto &v : j) {
    if (v.is_array()) for (auto &n : v) values.push_back(n.get<double>());
    else values.push_back(v.get<double>());
  }
  if (values.size()!=size_t(rows*cols)) throw std::runtime_error("calibration shape");
  cv::Mat m(rows,cols,CV_64F);
  std::copy(values.begin(),values.end(),m.ptr<double>());
  if (!cv::checkRange(m)) throw std::runtime_error("nonfinite calibration");
  return m;
}
tr::Calibration calibrationJson(const Json &j, const std::string &hash) {
  if (j.at("schema")!="b-calibration-v1-draft" || j.at("image_size_px")!=Json({1280,720}) ||
      j.at("square_size_m").get<double>()<=0 ||
      j.at("left_right_order")!="stitched_left=physical_left_camera, stitched_right=physical_right_camera")
    throw std::runtime_error("B requires metric original-eye stereo calibration");
  tr::Calibration c;
  c.K1=matrix(j.at("K_left"),3,3); c.K2=matrix(j.at("K_right"),3,3);
  c.D1=matrix(j.at("D_left"),1,int(j.at("D_left").size()));
  c.D2=matrix(j.at("D_right"),1,int(j.at("D_right").size()));
  c.R=matrix(j.at("R_left_to_right"),3,3); c.T=matrix(j.at("T_m"),3,1);
  c.R1=matrix(j.at("R1"),3,3); c.R2=matrix(j.at("R2"),3,3);
  c.P1=matrix(j.at("P1"),3,4); c.P2=matrix(j.at("P2"),3,4);
  // The reusable B core names its output frame "world" internally. Here its
  // identity transform is strictly the left-camera frame, never a table pose.
  c.Rcw=cv::Mat::eye(3,3,CV_64F); c.tcw=cv::Mat::zeros(3,1,CV_64F);
  c.world_valid=true; c.version=hash; c.provenance="left_camera_identity_transform";
  if(j.contains("diagnostic_world_pose")) {
    c.Rcw=matrix(j["diagnostic_world_pose"]["Rcw"],3,3);
    c.tcw=matrix(j["diagnostic_world_pose"]["tcw"],3,1);
    c.provenance="upright_world_diagnostic";
  }
  std::string why;
  if (!tr::validate_calibration(c,why)) throw std::runtime_error(why);
  return c;
}
tr::Calibration calibration(const Path &path,const std::string &hash) {
  return calibrationJson(Json::parse(readText(path)),hash);
}
ball::FrameStamp stamp(const FramePair &f, int eye, const std::string &cal) {
  return {f.meta.pair_id,static_cast<ball::Eye>(eye),f.meta.timestamp_ns,
          "original_eye_1280x720",f.meta.config_version,cal};
}
Json xyz(const std::optional<cv::Vec3d> &p) {
  if (!p) return nullptr;
  return {(*p)[0],(*p)[1],(*p)[2]};
}
struct Candidate {
  tr::PixelObservation pixel;
  std::string source;
  bool verified=false;
  Json quality=Json::object();
};
bool identity(const Meta &a,const Meta &b) {
  auto ja=metaJson(a), jb=metaJson(b);
  ja.erase("model_version"); jb.erase("model_version"); return ja==jb;
}
class BMeasurement final : public MeasurementModule {
public:
  BMeasurement() {
    auto path=measurementCalibration();
    if (path.empty()) if (const char *p=std::getenv("PIPELINE_B_CALIBRATION")) path=utf8Path(p);
    if (!path.empty()) {
      calibrationHash_=fileSha256(path); cal_=calibration(path,calibrationHash_);
    }
    geometry_.epipolar_px=3; geometry_.reprojection_px=5;
    relaxed_=std::getenv("PIPELINE_B_DIAGNOSTIC_RELAX") && std::string(std::getenv("PIPELINE_B_DIAGNOSTIC_RELAX"))=="1";
    geometry_.diagnostic_relaxed=relaxed_;
    if(relaxed_) { tr::TrackConfig cfg; cfg.gate_squared=1e30; tracker_=tr::Tracker(cfg); }
    events_.relaxed=relaxed_;
    events_.realtime=std::getenv("PIPELINE_B_LIVE_EVENTS") && std::string(std::getenv("PIPELINE_B_LIVE_EVENTS"))=="1";
  }
  bool tryOnlineCalibration(const Json &j,const std::string &hash) override {
    // Keep one immutable calibration throughout a held/toss/contact track.
    // No mixture of historical 3D positions from different stereo extrinsics.
    if(lastTrackActive_) return false;
    auto next=calibrationJson(j,hash);
    if(cal_ && (cv::norm(next.K1-cal_->K1)>1e-12 || cv::norm(next.K2-cal_->K2)>1e-12 ||
       cv::norm(next.D1-cal_->D1)>1e-12 || cv::norm(next.D2-cal_->D2)>1e-12 ||
       std::abs(cv::norm(next.T)-cv::norm(cal_->T))>1e-10 ||
       cv::norm(next.Rcw-cal_->Rcw)>1e-12 || cv::norm(next.tcw-cal_->tcw)>1e-12))
      throw std::runtime_error("TESO attempted to change intrinsics, baseline length or left world pose");
    minimumOnlinePair_=last_?last_->pair_id+1:0;
    updates_.push_back({{"kind","online_calibration_boundary"},{"minimum_pair_id",minimumOnlinePair_},
      {"old_calibration_sha256",calibrationHash_},{"new_calibration_sha256",hash},
      {"history_policy","clear_idle_track_and_reject_pre_boundary_AI"}});
    tracker_.clear();events_.clear();history_.clear();sources_.clear();pending_.clear();
    ++trackId_;lastTrackActive_=false;cal_=std::move(next);calibrationHash_=hash;
    return true;
  }
  void acceptDetections(const std::vector<DetectionResult> &items) override {
    for (auto &r:items) {
      if(r.meta.pair_id<minimumOnlinePair_) continue;
      auto it=sources_.find(r.meta.pair_id);
      if(it==sources_.end()) {
        // Legacy synchronous callers may deliver results before process().
        if(r.status=="ok" && (!last_ || r.meta.pair_id>last_->pair_id))
          pending_[{r.meta.pair_id,int(r.eye)}]=r;
        continue;
      }
      auto &s=it->second;
      if(Clock::now()-s.retained>std::chrono::seconds(2)) {
        updates_.push_back({{"kind","late_context_expired"},{"source_pair_id",r.meta.pair_id}});
        sources_.erase(it); continue;
      }
      if(r.status!="ok" || !identity(r.meta,s.frame->meta) ||
         (r.eye!=Eye::Left && r.eye!=Eye::Right)) continue;
      bool valid=true;
      for(int e=0;e<2;++e) valid &= r.reference_id[e]==s.motion.eyes[e].reference_id &&
        r.reference_valid[e]==s.motion.eyes[e].reference_valid &&
        r.reference_timestamp_ns[e]==s.motion.eyes[e].reference_timestamp_ns;
      if(!valid) continue;
      s.results[int(r.eye)]=r;
      if(s.results.size()!=2) continue;
      std::optional<tr::WorldObservation> observation;
      std::vector<DetectionResult> stereo={s.results.at(0),s.results.at(1)};
      const double sourceAge=std::chrono::duration<double,std::milli>(Clock::now()-s.retained).count();
      for(auto &r:stereo)r.diagnostics["source_age_ms"]=sourceAge;
      auto measured=evaluate(*s.frame,s.motion,stereo,observation,nullptr);
      events_.update(measured,*s.frame,stereo,observation,calibrationHash_,&s.motion);
      rememberFlight(measured,s.frame->meta.pair_id);
      revise(s.frame->meta.pair_id,std::move(measured),observation);
      sources_.erase(it);
    }
    while(pending_.size()>32) pending_.erase(pending_.begin());
  }
  void retainDetectionFrame(FramePtr f,const MotionResult &m) override {
    if(!f || !m.valid || !identity(f->meta,m.meta)) return;
    MotionResult thin=m;
    for(int e=0;e<2;++e) {
      thin.eyes[e].stages={};
      thin.eyes[e].stages[6]=m.eyes[e].stages[6].clone();
    }
    auto id=f->meta.pair_id;
    sources_[id]={std::move(f),std::move(thin),Clock::now(),{}};
    while(sources_.size()>8) sources_.erase(sources_.begin());
  }
  void discardDetectionFrame(const Meta &m) override {
    auto it=sources_.find(m.pair_id);
    if(it!=sources_.end() && identity(it->second.frame->meta,m)) sources_.erase(it);
  }
  std::vector<Json> takeUpdates() override {
    auto result=std::move(updates_); updates_.clear(); return result;
  }
  Json process(const FramePair &f,const MotionResult &m,const std::vector<DetectionResult> &rs) override {
    auto begin=Clock::now();
    if(last_ && (f.meta.pair_id<=last_->pair_id || f.meta.timestamp_ns<=last_->timestamp_ns ||
       f.meta.config_version!=last_->config_version || f.meta.source!=last_->source ||
       f.meta.calibration_version!=last_->calibration_version)) {
      tracker_.clear(); events_.clear(); pending_.clear(); sources_.clear(); history_.clear();
      ++trackId_; lastTrackActive_=false; latestFlight_=nullptr;
    }
    std::vector<DetectionResult> records=rs;
    for(auto &p:pending_) if(p.first.first==f.meta.pair_id) records.push_back(p.second);
    std::optional<tr::WorldObservation> observation;
    auto out=evaluate(f,m,records,observation,&tracker_);
    if(!cal_ || !m.valid || !identity(f.meta,m.meta)) return out;
    History row{stamp(f,0,calibrationHash_),observation,out,tracker_.checkpoint(),
                trackId_,lastTrackActive_,0};
    applyTrack(row.output,row.stamp,row.observation,tracker_,trackId_,lastTrackActive_);
    events_.update(row.output,f,records,observation,calibrationHash_,&m);
    rememberFlight(row.output,f.meta.pair_id);
    row.output["revision"]=0;
    row.output["processing_ms"]=std::chrono::duration<double,std::milli>(Clock::now()-begin).count();
    out=row.output;
    history_.push_back(std::move(row));
    while(history_.size()>64) history_.pop_front();
    last_=f.meta;
    for(auto it=pending_.begin();it!=pending_.end();)
      if(it->first.first<=f.meta.pair_id) it=pending_.erase(it); else ++it;
    return out;
  }
  bool requestRightDetection(const FramePair &,const MotionResult &) const override { return true; }
  std::string version() const override { return cal_?"b-pr26-camera-measure-track-integration-v0.3":"unavailable"; }
private:
  struct Source {
    FramePtr frame; MotionResult motion; Clock::time_point retained;
    std::map<int,DetectionResult> results;
  };
  struct History {
    ball::FrameStamp stamp;
    std::optional<tr::WorldObservation> observation;
    Json output;
    tr::Tracker before;
    uint64_t track_before;
    bool active_before;
    uint64_t revision;
  };
  void rememberFlight(Json &out,uint64_t pair) {
    if(out.contains("events") && out["events"].value("fit_valid",false))
      latestFlight_={{"reported_at_pair_id",pair},{"measurement_calibration_sha256",calibrationHash_},{"event",out["events"]}};
    out["latest_valid_flight"]=latestFlight_;
  }
  void applyTrack(Json &out,const ball::FrameStamp &st,
                         const std::optional<tr::WorldObservation> &observation,
                         tr::Tracker &tracker,uint64_t &trackId,bool &wasActive) {
    // Heatmap-only geometry is retained for inspection; it cannot initialize
    // a trajectory or propagate predictions without measurements in both eyes.
    auto eligible=out.value("tracking_eligible",false)?observation:std::nullopt;
    auto result=tracker.update(st,eligible,false); // camera gravity direction unknown
    if(result.reset || (result.accepted && !wasActive)) ++trackId;
    bool active=bool(result.filtered) || bool(result.predicted);
    out["track_state"]=result.accepted?"observed":(result.predicted?"predicted":"invalid");
    out["status"]=observation?"observed":out["track_state"].get<std::string>();
    out["pairing_status"]=observation?"observed":"invalid";
    out["track_reason"]=result.reason;
    out["track_id"]=active?Json(trackId):Json(nullptr);
    out["filtered_xyz_m"]=xyz(result.filtered); out["predicted_xyz_m"]=xyz(result.predicted);
    out["velocity_m_s"]=xyz(result.velocity); out["dt_s"]=result.dt;
    for(int e=0;e<2;++e) {
      auto p=result.predicted?tr::project(*result.predicted,static_cast<ball::Eye>(e),*cal_):std::nullopt;
      out[e?"right_prediction_pixel":"left_prediction_pixel"]=p?Json({p->x,p->y}):Json(nullptr);
    }
    wasActive=active;
  }
  void revise(uint64_t id,Json measured,const std::optional<tr::WorldObservation> &observation) {
    if(!observation) {
      updates_.push_back({{"kind","late_measurement_rejected"},{"source_pair_id",id},
                          {"measurement",std::move(measured)}}); return;
    }
    auto first=std::find_if(history_.begin(),history_.end(),[&](const auto &h){return h.stamp.pair_id==id;});
    if(first==history_.end()) {
      updates_.push_back({{"kind","late_geometry_outside_track_window"},{"source_pair_id",id},
                          {"tracker_revised",false},{"measurement",std::move(measured)}}); return;
    }
    // A valid same-frame pixel measurement stays the primary observation.
    // Pixel shape verification alone cannot establish that a blob is the ball.
    if(first->observation && first->output.value("semantic_ball_supported",false)) return;
    first->observation=observation; first->output=std::move(measured);
    auto replay=first->before.checkpoint();
    auto track=first->track_before; bool active=first->active_before;
    for(auto it=first;it!=history_.end();++it) {
      it->before=replay.checkpoint(); it->track_before=track; it->active_before=active;
      applyTrack(it->output,it->stamp,it->observation,replay,track,active);
      it->output["revision"]=++it->revision;
      updates_.push_back({{"schema_version",1},{"kind","measurement_revision"},
        {"source_pair_id",it->stamp.pair_id},{"cause_pair_id",id},
        {"timestamp_ns",it->stamp.sample_time_ns},{"revision",it->revision},
        {"published_ns",monotonicNs()},{"tracker_revised",true},{"measurement",it->output}});
    }
    tracker_=replay.checkpoint(); trackId_=track; lastTrackActive_=active;
    if(updates_.size()>512) throw std::runtime_error("B update consumer must drain bounded revisions");
  }
  Json evaluate(const FramePair &f,const MotionResult &m,const std::vector<DetectionResult> &records,
                std::optional<tr::WorldObservation> &observation,const tr::Tracker *guide) {
    Json out=metaJson(f.meta);
    out.update({{"version",version()},{"coordinate_frame",cal_&&cal_->provenance=="upright_world_diagnostic"?"world":"left_camera"},{"unit","m"},
      {"world_transform_available",cal_&&cal_->provenance=="upright_world_diagnostic"},{"measurement_calibration_sha256",calibrationHash_},
      {"status","invalid"},{"camera_xyz_m",nullptr},{"filtered_xyz_m",nullptr},
      {"predicted_xyz_m",nullptr},{"velocity_m_s",nullptr},{"observations",Json::array()},
      {"reference_id",{m.eyes[0].reference_id,m.eyes[1].reference_id}},
      {"reference_valid",{m.eyes[0].reference_valid,m.eyes[1].reference_valid}},
      {"reference_timestamp_ns",{m.eyes[0].reference_timestamp_ns,m.eyes[1].reference_timestamp_ns}}});
    out["measurement_algorithm_version"]="b-measure-v2-draft";
    out["measurement_behavior_version"]="unified-world-throw-diagnostic-20261024";
    out["diagnostic_relaxed"]=relaxed_;
    out["disabled_quality_gates"]=relaxed_?Json({"epipolar_3px","reprojection_5px","diameter_ratio","min_disparity_quality","depth_range_quality","pair_ambiguity","prediction_24px","kalman_innovation","ROI_shape_rejection_with_box_fallback","flight_fit_30mm_residual"}):Json::array();
    out["tracking_eligible"]=false;
    out["measurement_primary_path"]="same_frame_motion_mask_original_roi";
    if (!cal_) { out["reason"]="calibration_unavailable"; return out; }
    if (!identity(f.meta,m.meta) || !m.valid) { out["reason"]="motion_identity_or_validity"; return out; }
    auto st=stamp(f,0,calibrationHash_);
    std::array<std::vector<Candidate>,2> candidates;
    std::array<std::vector<Candidate>,2> semantic;
    out["semantic_ball_supported"]=false;
    out["events"]={{"status","unavailable"},{"reason","event_core_not_connected_to_validated_world_frame"}};
    // Config names describe different layers. Bind the image identity to A's
    // validated frame config; keep B's algorithm version separately above.
    auto imageConfig=ballConfig_; imageConfig.config_version=f.meta.config_version;
    for(int e=0;e<2;++e) {
      auto s=stamp(f,e,calibrationHash_);
      ball::GrayFrame image{f.original[e],s};
      ball::MotionFrame mask{m.eyes[e].stages[6],s,m.valid,m.eyes[e].reference_valid,
                            m.eyes[e].reference_id,m.error};
      auto hint=guide?guide->roi_hint(s,static_cast<ball::Eye>(e),*cal_,false):std::nullopt;
      auto measured=ball::measure_eye(image,mask,imageConfig,hint);
      Json attempts=Json::array();
      for(const auto &a:measured.attempts) attempts.push_back({
        {"reason",a.reason},{"source",ball::to_string(a.source)},
        {"seed_image_center",{a.seed_image_center.x,a.seed_image_center.y}},
        {"area",a.area},{"circularity",a.circularity},{"flags",a.quality.flags}});
      out[e?"right_roi_attempts":"left_roi_attempts"]=std::move(attempts);
      for(auto &p:tr::observation_candidates(measured))
        candidates[e].push_back({p,"motion_mask_original_roi_centroid",true,
                                {{"pixel_evidence_verified",true}}});
      out[e?"right_measurement_reason":"left_measurement_reason"]=measured.reason;
    }
    std::set<int> seenEyes;
    std::string modelVersion;
    for (auto &d:records) {
      int e=int(d.eye);
      if (e<0 || e>1 || seenEyes.count(e) || d.status!="ok" || !identity(d.meta,f.meta)) continue;
      bool reference=true;
      for(int k=0;k<2;++k) reference &= d.reference_id[k]==m.eyes[k].reference_id &&
          d.reference_valid[k]==m.eyes[k].reference_valid &&
          d.reference_timestamp_ns[k]==m.eyes[k].reference_timestamp_ns;
      if(!reference) continue;
      if(!modelVersion.empty() && modelVersion!=d.meta.model_version) continue;
      modelVersion=d.meta.model_version;
      seenEyes.insert(e);
      out["model_version"]=d.meta.model_version; out["model_source"]=d.backend;
      for (auto &box:d.boxes) {
        if(box.value("class","")!="ball") continue;
        const bool detectorBox=box.value("bbox_semantics","")=="detector_box";
        std::vector<double> point;
        cv::Rect2d proposal;
        if(detectorBox) {
          auto q=box.at("bbox").get<std::vector<double>>();
          if(q.size()!=4 || !std::all_of(q.begin(),q.end(),[](double v){return std::isfinite(v);}) ||
             q[0]<0 || q[1]<0 || q[2]<=0 || q[3]<=0 || q[0]+q[2]>EyeWidth || q[1]+q[3]>EyeHeight) continue;
          proposal={q[0],q[1],q[2],q[3]};
          // A detector midpoint is a search seed, never a measured ball center.
          point={q[0]+q[2]*.5,q[1]+q[3]*.5};
        } else {
          if(!box.contains("center")) continue;
          point=box.at("center").get<std::vector<double>>();
        }
        if(point.size()!=2 || !std::isfinite(point[0]) || !std::isfinite(point[1]) ||
           point[0]<0 || point[0]>=EyeWidth || point[1]<0 || point[1]>=EyeHeight) continue;
        Candidate c; c.pixel.stamp=stamp(f,e,calibrationHash_);
        c.pixel.center={point[0],point[1]}; c.source="c_candidate_geometry";
        ball::Candidate seed; seed.search_center={float((point[0]-.5)*.5),float((point[1]-.5)*.5)};
        auto measured=ball::measure_ball(f.original[e],seed,ballConfig_);
        const bool refined=measured.source==ball::MeasurementSource::Observed &&
                           (!detectorBox || proposal.contains(measured.image_center));
        if(detectorBox) {
          auto key=e?"right_semantic_roi_attempts":"left_semantic_roi_attempts";
          if(!out.contains(key)) out[key]=Json::array();
          out[key].push_back({{"bbox",box.at("bbox")},{"seed_center",point},
            {"pixel_evidence_verified",refined},{"reason",measured.reason},
            {"refined_center_in_detector_box",measured.source==ball::MeasurementSource::Observed && proposal.contains(measured.image_center)},
            {"audit_area",measured.area},{"audit_circularity",measured.circularity},
            {"audit_otsu",measured.otsu_threshold},{"audit_contrast",measured.quality.contrast},
            {"audit_aspect",measured.quality.aspect_ratio},
            {"audit_center",measured.source==ball::MeasurementSource::Observed ? Json({measured.image_center.x,measured.image_center.y}) : Json(nullptr)}});
          // Failed local measurement must not create geometry from a box midpoint.
          if(!refined && !relaxed_) continue;
        }
        if(refined) {
          c.pixel.center=measured.image_center; c.pixel.diameter_px=0;
          c.verified=true; c.source=detectorBox?"c_yolo_box_original_roi_centroid":"c_hint_original_roi_centroid";
        }
        c.quality={{"roi_reason",measured.reason},{"pixel_evidence_verified",c.verified}};
        if(!refined && detectorBox) c.source="c_yolo_box_center_approximate";
        semantic[e].push_back(c);
      }
    }
    // Keep both proposal sources. A wrong model box must not erase a good
    // image measurement, and an existing blob must not hide the model hint.
    const bool hasSemantic=!semantic[0].empty() || !semantic[1].empty();
    for(int e=0;e<2;++e) for(auto &c:semantic[e]) {
      auto duplicate=std::find_if(candidates[e].begin(),candidates[e].end(),[&](const auto &p){
        return cv::norm(c.pixel.center-p.pixel.center)<2;
      });
      if(duplicate==candidates[e].end()) candidates[e].push_back(c);
      else if(c.verified) *duplicate=c;
    }
    std::array<std::vector<tr::PixelObservation>,2> pixels;
    for(int e=0;e<2;++e) {
      Json points=Json::array();
      for(auto &c:candidates[e]) {
        pixels[e].push_back(c.pixel);
        points.push_back({{"center",{c.pixel.center.x,c.pixel.center.y}},
          {"source",c.source},{"pixel_verified",c.verified}});
      }
      out[e?"right_candidates":"left_candidates"]=std::move(points);
    }
    // Ball semantics own the diagnostic trajectory; background blobs cannot initialize it.
    if(relaxed_) for(int e=0;e<2;++e) {
      candidates[e]=semantic[e]; pixels[e].clear();
      for(const auto& c:candidates[e]) pixels[e].push_back(c.pixel);
    }
    auto prediction=guide && !hasSemantic?guide->predict(st,false):std::nullopt;
    std::array<std::vector<tr::PixelObservation>,2> verifiedPixels;
    std::array<std::vector<size_t>,2> verifiedIndices;
    for(int e=0;e<2;++e) for(size_t k=0;k<candidates[e].size();++k) if(candidates[e][k].verified) {
      verifiedPixels[e].push_back(candidates[e][k].pixel); verifiedIndices[e].push_back(k);
    }
    out["audit_stereo_pairs"]=Json::array();
    for(size_t li=0;li<candidates[0].size();++li) for(size_t ri=0;ri<candidates[1].size();++ri) {
      auto diagnostic=tr::triangulate(candidates[0][li].pixel,candidates[1][ri].pixel,*cal_,geometry_);
      out["audit_stereo_pairs"].push_back({{"left_index",li},{"right_index",ri},
        {"valid",diagnostic.valid},{"reason",diagnostic.reason},
        {"epipolar_error_px",diagnostic.epipolar_error_px},{"disparity_px",diagnostic.disparity_px},
        {"reprojection_error_px",diagnostic.reprojection_error_px}});
    }
    auto match=tr::match_stereo(verifiedPixels[0],verifiedPixels[1],*cal_,prediction,geometry_);
    if(match.valid) {
      match.left_index=verifiedIndices[0][match.left_index];
      match.right_index=verifiedIndices[1][match.right_index];
    } else match=tr::match_stereo(pixels[0],pixels[1],*cal_,prediction,geometry_);
    if(match.valid) {
      observation=match.observation;
      auto &a=candidates[0][match.left_index], &b=candidates[1][match.right_index];
      out["camera_xyz_m"]={observation->camera[0],observation->camera[1],observation->camera[2]};
      out["left_pixel"]={a.pixel.center.x,a.pixel.center.y};
      out["right_pixel"]={b.pixel.center.x,b.pixel.center.y};
      out["measurement_source"]={a.source,b.source};
      out["pixel_evidence_verified"]=a.verified && b.verified;
      out["semantic_ball_supported"]=a.source!="motion_mask_original_roi_centroid" &&
                                      b.source!="motion_mask_original_roi_centroid";
      out["tracking_eligible"]=(a.verified && b.verified) || (relaxed_ && out.value("semantic_ball_supported",false));
      out["world_xyz_m"]={observation->world[0],observation->world[1],observation->world[2]};
      out["measurement_accuracy_validated"]=false;
      out["epipolar_error_px"]=observation->epipolar_error_px;
      out["reprojection_error_px"]=observation->reprojection_error_px;
      out["disparity_px"]=observation->disparity_px;
      out["observations"]={{{"eye","left"},{"center_px",out["left_pixel"]},{"quality",a.quality}},
                           {{"eye","right"},{"center_px",out["right_pixel"]},{"quality",b.quality}}};
    }
    out["pairing_status"]=match.valid?"observed":"invalid";
    out["reason"]=match.reason;
    out["candidate_count"]={candidates[0].size(),candidates[1].size()};
    return out;
  }
  uint64_t minimumOnlinePair_=0;
  bool relaxed_=false;
  Json latestFlight_=nullptr;
  DiagnosticEvents events_;
  std::optional<tr::Calibration> cal_;
  std::string calibrationHash_;
  ball::Config ballConfig_;
  tr::GeometryConfig geometry_;
  tr::Tracker tracker_;
  std::optional<Meta> last_;
  uint64_t trackId_=0;
  bool lastTrackActive_=false;
  std::map<std::pair<uint64_t,int>,DetectionResult> pending_;
  std::map<uint64_t,Source> sources_;
  std::deque<History> history_;
  std::vector<Json> updates_;
};
}
void register_b_module(Registry &registry) {
  registry.measurement=[] { return std::make_unique<BMeasurement>(); };
}
} // namespace pipeline
