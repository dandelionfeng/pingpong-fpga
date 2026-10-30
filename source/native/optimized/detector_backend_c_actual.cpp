// Native V2.4 bridge with V2.1 configuration compatibility. Original-eye pixels.
#include "c_perception_engine.hpp"
#include "runtime_session.hpp"
#include "pipeline/hand_schedule.hpp"
#include "pipeline/pipeline.hpp"
#include <optional>
#include "internal_onnx.hpp"
#include "specialist_detector.hpp"

namespace pipeline {
namespace {
class CPerceptionDetector final : public DetectorBackend {
public:
  explicit CPerceptionDetector(const Path &configPath) {
    if (configPath.empty())
      throw std::runtime_error(
          "C model configuration is required (--model-config)");
    auto j = Json::parse(readText(configPath));
    interfaceVersion_ = j.at("interface_version").get<std::string>();
    if (interfaceVersion_ != "C_ACTUAL_INTERFACE_V2_1" &&
        interfaceVersion_ != "C_ACTUAL_INTERFACE_V2_3" &&
        interfaceVersion_ != "C_ACTUAL_INTERFACE_V2_4" &&
        interfaceVersion_ != "C_ACTUAL_INTERFACE_V2_4_UNIFIED_ALL_1")
      throw std::runtime_error("C interface version mismatch");
    c_actual::ModelPaths paths;
    v6_=j.value("detector_mode",std::string("split"))=="v6_ball_unified_hand_racket";
    all_ = v6_ || j.value("detector_mode", std::string("split")) == "unified_all";
    if (all_ != (interfaceVersion_ == "C_ACTUAL_INTERFACE_V2_4_UNIFIED_ALL_1"))
      throw std::runtime_error("Single-YOLO ball semantics require the local UNIFIED_ALL_1 interface");
    paths.unified_all_classes = all_;
    unified_ = all_ || j.value("detector_mode", std::string("split")) == "unified";
    if (j.value("detector_mode", std::string("split")) != "split" && !unified_)
      throw std::runtime_error("C detector_mode must be split or unified");
    if (unified_ && !all_ && interfaceVersion_ != "C_ACTUAL_INTERFACE_V2_4")
      throw std::runtime_error("Unified mode requires C_ACTUAL_INTERFACE_V2_4");
    const std::vector<std::string> keys = v6_ ? std::vector<std::string>{"unified","v6_ball"} : all_ ? std::vector<std::string>{"unified"}
                                      : unified_ ? std::vector<std::string>{"ball", "unified"}
                                                 : std::vector<std::string>{"ball", "hand", "racket"};
    for (const auto &key : keys) {
      auto record = j.at("models").at(key);
      auto path = utf8Path(record.at("path").get<std::string>());
      if (path.is_relative())
        path = configPath.parent_path() / path;
      auto sha = fileSha256(path);
      if (sha != record.at("sha256").get<std::string>())
        throw std::runtime_error(std::string("C model SHA256 mismatch: ") +
                                 key);
      modelHashes_[key] = sha;
      if (std::string(key) == "ball")
        paths.ball_track = pathUtf8(path);
      else if (std::string(key) == "hand")
        paths.hand = pathUtf8(path);
      else if (key == "v6_ball") v6Path_=pathUtf8(path);
      else if (key == "racket")
        paths.racket = pathUtf8(path);
      else
        paths.unified = pathUtf8(path);
    }
    c_actual::Config config;
    // Frozen preprocessing/thresholds. Only CPU thread count is configurable.
    config.intra_op_threads = j.value("intra_op_threads", 2);
    if (config.intra_op_threads < 1 || config.intra_op_threads > 16)
      throw std::runtime_error("C intra_op_threads must be 1..16");
    if(j.contains("diagnostic_thresholds")) {
      const auto &d=j.at("diagnostic_thresholds");
      config.base_conf=d.value("base_conf",config.base_conf);
      config.yolo_ball_conf=d.value("ball",config.yolo_ball_conf);
      config.hand_conf=d.value("hand",config.hand_conf);
      config.racket_conf=d.value("racket",config.racket_conf);
      for(double v:{double(config.base_conf),double(config.yolo_ball_conf),double(config.hand_conf),double(config.racket_conf)})
        if(!std::isfinite(v)||v<0||v>1) throw std::runtime_error("invalid diagnostic confidence");
    }
    thresholds_={{"ball",config.yolo_ball_conf},{"hand",config.hand_conf},{"racket",config.racket_conf},{"base_conf",config.base_conf},{"nms_iou",config.iou}};
    if(v6_) {
      v6Confidence_=j.value("v6_ball_conf",.10f);
      if(!std::isfinite(v6Confidence_)||v6Confidence_<0||v6Confidence_>1)throw std::runtime_error("invalid V6 confidence");
      auto ballConfig=config;ballConfig.base_conf=v6Confidence_;
      for(auto &detector:v6Detectors_) {
        std::string why;
        if(!detector.load(v6Path_,{"ball"},ballConfig,false,&why) || detector.numClasses()!=1)
          throw std::runtime_error("V6 single-ball model load failed: "+why);
      }
    }
    modelVersion_ = interfaceVersion_ + ":" + (v6_ ? "v6_ball_unified_hand_racket:" : all_ ? "unified_all:" : unified_ ? "unified:" : "split:") + modelHashes_.dump()+":thresholds:"+thresholds_.dump()+(v6_?":v6_conf="+std::to_string(v6Confidence_):"");
    for (auto &engine : engines_) {
      std::string error;
      if (!engine.load(paths, config, &error))
        throw std::runtime_error(error);
    }
  }
  DetectionResult infer(const DetectorContext &c, const std::atomic<bool> &stop,
                        int timeoutMs) override {
    DetectionResult r;
    r.meta = c.meta;
    r.meta.model_version = modelVersion_;
    r.eye = c.eye;
    r.task_id = c.task_id;
    r.generation = c.generation;
    r.reference_id = c.reference_id;
    r.reference_timestamp_ns = c.reference_timestamp_ns;
    r.reference_valid = c.reference_valid;
    r.backend = mode();
    if (stop) {
      r.status = "cancelled";
      return r;
    }
    if (c.gray.empty() || c.gray.type() != CV_8UC1 || c.origin != cv::Point{} ||
        c.gray.size() != c.original_size) {
      r.status = "invalid: C requires full original-eye GRAY8";
      return r;
    }
    const auto e = static_cast<size_t>(c.eye);
    const auto timestamp = c.meta.eye_timestamp_ns[e] > 0
                               ? c.meta.eye_timestamp_ns[e]
                               : c.meta.timestamp_ns;
    auto &previous = previous_[e];
    bool reset = !previous || previous->generation != c.generation ||
                 previous->id + 1 != c.meta.camera_frame_id[e] ||
                 timestamp <= previous->timestamp ||
                 previous->size != c.gray.size() ||
                 previous->source != c.meta.source ||
                 previous->config != c.meta.config_version ||
                 previous->calibration != c.meta.calibration_version;
    if (reset)
      engines_[e].reset();
    previous = Continuity{c.generation,
                          c.meta.camera_frame_id[e],
                          timestamp,
                          c.gray.size(),
                          c.meta.source,
                          c.meta.config_version,
                          c.meta.calibration_version};
    c_actual::FrameMeta meta;
    meta.frame_id = c.meta.camera_frame_id[e];
    meta.timestamp = timestamp / 1e9;
    meta.submitted_ns = c.submitted_ns;
    meta.has_reference = c.reference_valid[e];
    meta.reference_id = c.reference_id[e];
    meta.reference_timestamp_ns = c.reference_timestamp_ns[e];
    auto window=c.detector_history;
    if(window && !all_) {
      if(window->previous_meta.size()!=window->previous[e].size())
        throw std::runtime_error("temporal metadata/gray length mismatch");
      auto next=c.meta;
      for(auto it=window->previous_meta.rbegin();it!=window->previous_meta.rend();++it) {
        if(it->camera_frame_id[e]+1!=next.camera_frame_id[e] || it->timestamp_ns>=next.timestamp_ns ||
            it->source!=c.meta.source || it->config_version!=c.meta.config_version ||
            it->calibration_version!=c.meta.calibration_version)
          throw std::runtime_error("nonconsecutive or foreign temporal frame");
        next=*it;
      }
    }
    const int handStride=std::getenv("CHAIN_HAND_STRIDE")?std::stoi(std::getenv("CHAIN_HAND_STRIDE")):1;
    if(handStride<1||handStride>30)throw std::runtime_error("Invalid hand invocation stride");
    if(!scheduledPair_ || *scheduledPair_!=c.meta.pair_id) {
      scheduledPair_=c.meta.pair_id;
      handReason_=handKinematicConfirmed.load()?"kinematic_candidate":handMaskConfirmed.load()?"mask_confirmed":"stride";
      handRun_=!v6_ || (!handKinematicConfirmed.load() && !handMaskConfirmed.load() && handGroups_++%handStride==0);
    }
    c_actual::resetRuntimeTimings();
    auto p = window && !all_ ? engines_[e].inferGrayWindow(c.gray,meta,window->background[e],window->previous[e])
                    : handRun_?engines_[e].inferGray(c.gray, meta):c_actual::PerceptionResult{};
    if(v6_) {
      const auto started=Clock::now();std::string why;
      p.balls=v6Detectors_[e].detect(c_actual::preprocess::grayToGray3(c.gray),v6Confidence_,c.gray.cols,c.gray.rows,&why);
      if(!why.empty())throw std::runtime_error("V6 inference failed: "+why);
      p.ball_model=v6Path_;
      p.infer_ms+=std::chrono::duration<double,std::milli>(Clock::now()-started).count();
    }
    r.diagnostics = {{"interface_version", interfaceVersion_},
                     {"ball_state", c_actual::to_string(p.ball.state)},
                     {"ball_detected", p.ball.detected},
                     {"history_reset", reset},
                     {"background", "first_frame"},
                     {"infer_ms", p.infer_ms},
                     {"model_sha256", modelHashes_},
                     {"warnings", p.warnings}};
    r.diagnostics["detector_mode"] = v6_ ? "v6_ball_unified_hand_racket" : all_ ? "unified_all" : unified_ ? "unified" : "split";
    r.diagnostics["ball_source"] = v6_ ? "V6_Round2_YOLO" : all_ ? "YOLOv8n_unified" : "BallTrack";
    r.diagnostics["unified_ball_output_used"] = all_ && !v6_;
    if (all_) {
      r.diagnostics["ball_state"] = p.balls.empty() ? "DROPOUT" : "DETECTED";
      r.diagnostics["ball_detected"] = !p.balls.empty();
      r.diagnostics["background"] = "not_used";
      r.diagnostics["yolo_ball_conf"] = v6_?Json(v6Confidence_):thresholds_["ball"]; r.diagnostics["diagnostic_thresholds"]=thresholds_;
      r.diagnostics["active_graphs_per_eye"] = v6_?1+int(handRun_):1;
      r.diagnostics["yolo_forward_passes"] = v6_?1+int(handRun_):1;
      r.diagnostics["hand_racket_invoked"] = handRun_;
      r.diagnostics["hand_racket_skip_reason"] = handRun_?"invoked":handReason_;
      r.diagnostics["hand_stride"] = handStride;
    }
    r.diagnostics["hand_input_size"] = engines_[e].debugHandInputSize();
    r.diagnostics["racket_input_size"] = engines_[e].debugRacketInputSize();
    r.diagnostics["engine_version"] = engines_[e].versionString();
    r.diagnostics["temporal_input"]=all_?"not_used_single_frame":window?"capture_window_before_queue_drop":"legacy_inference_history";
    if(window && !all_) {
      r.diagnostics["history_camera_frame_ids"]=Json::array();
      for(const auto &m:window->previous_meta) r.diagnostics["history_camera_frame_ids"].push_back(m.camera_frame_id[e]);
    }
    for (const auto &warning : p.warnings)
      if (warning.find("MISMATCH") != std::string::npos || warning.find("YOLO_INFERENCE_FAILED") != std::string::npos || warning.find("YOLO_INVALID") != std::string::npos) {
        r.status = "invalid: " + warning;
        return r;
      }
    r.diagnostics["inference_runtime"] = "rk3576-rknn-npu";
    r.diagnostics["rknn_graph_ms"] = c_actual::lastRuntimeTimings();
    if (!all_ && p.ball.state == c_actual::BallState::kInvalid) {
      r.status = "invalid: BallTrack inference failed";
      return r;
    }
    if (p.ball.state == c_actual::BallState::kDetected && p.ball.detected) {
      if (!p.ball.has_region || p.ball.region.width <= 0 ||
          p.ball.region.height <= 0)
        throw std::runtime_error("C detected ball has no heatmap component");
      r.boxes.push_back({{"class", "ball"},
                         {"confidence", p.ball.confidence},
                         {"state", "DETECTED"},
                         {"observation", "observed"},
                         {"detected", true},
                         {"center", {p.ball.center.x, p.ball.center.y}},
                         {"bbox",
                          {p.ball.region.x, p.ball.region.y,
                           p.ball.region.width, p.ball.region.height}},
                         {"bbox_semantics", "heatmap_component"}});
    }
    for (const auto *boxes : {&p.balls, &p.hands, &p.rackets})
      for (const auto &b : *boxes)
        r.boxes.push_back({{"class", b.class_name},
                           {"confidence", b.confidence},
                           {"bbox", {b.x, b.y, b.w, b.h}},
                           {"bbox_semantics", "detector_box"},
                           {"observation", "observed"}});
    // Synchronous ORT cannot preempt a graph; discard late/cancelled
    // completions.
    if (stop)
      r.status = "cancelled";
    else if (p.infer_ms > timeoutMs)
      r.status = "expired";
    if (r.status != "ok")
      r.boxes = Json::array();
    return r;
  }
  std::string mode() const override { return all_ ? "actual-model-c-actual-v2.4-unified-all" : unified_ ? "actual-model-c-actual-v2.4-unified" : "actual-model-c-actual-v2"; }

private:
  std::optional<uint64_t> scheduledPair_;
  uint64_t handGroups_=0;
  bool handRun_=true;
  std::string handReason_;
  struct Continuity {
    uint64_t generation, id;
    int64_t timestamp;
    cv::Size size;
    std::string source, config, calibration;
  };
  bool v6_=false;
  float v6Confidence_=.10f;
  std::string v6Path_;
  std::array<c_actual::YoloDetector,2> v6Detectors_;
  std::array<c_actual::CPerceptionEngine, 2> engines_;
  std::array<std::optional<Continuity>, 2> previous_;
  Json modelHashes_;
  Json thresholds_;
  std::string modelVersion_, interfaceVersion_;
  bool unified_ = false;
  bool all_ = false;
};
} // namespace
void register_c_module(Registry &registry) {
  registry.detector = [] {
    auto path=detectorConfiguration();
    auto j=Json::parse(readText(path));
    if(j.value("detector_mode",std::string())=="specialists_v6_hand_v3_racket")
      return std::unique_ptr<DetectorBackend>(std::make_unique<SpecialistDetector>(path));
    return std::unique_ptr<DetectorBackend>(std::make_unique<CPerceptionDetector>(path));
  };
}
} // namespace pipeline
