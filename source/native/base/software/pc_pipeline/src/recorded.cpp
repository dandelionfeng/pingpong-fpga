#include "pipeline/recorded.hpp"
#include <sstream>
namespace pipeline {
namespace {
void require(bool ok, const std::string &why) {
  if (!ok) throw std::runtime_error("recorded detections: " + why);
}
void boxes(const Json &items) {
  require(items.is_array(), "boxes must be an array");
  for (auto &b : items) {
    auto cls = b.at("class").get<std::string>();
    require(cls == "ball" || cls == "hand" || cls == "racket", "unknown class");
    auto q = b.at("bbox").get<std::vector<double>>();
    double score = b.at("confidence");
    require(q.size() == 4 && std::isfinite(score) && score >= 0 && score <= 1,
            "invalid box/score");
    for (auto v : q) require(std::isfinite(v), "nonfinite box");
    require(q[0] >= 0 && q[1] >= 0 && q[2] > 0 && q[3] > 0 &&
            q[0]+q[2] <= EyeWidth && q[1]+q[3] <= EyeHeight, "box outside eye");
    if (b.contains("center")) {
      auto p = b.at("center").get<std::vector<double>>();
      require(p.size() == 2 && std::isfinite(p[0]) && std::isfinite(p[1]) &&
              p[0] >= 0 && p[0] < EyeWidth && p[1] >= 0 && p[1] < EyeHeight,
              "invalid center");
    }
  }
}
}
RecordedDetections::RecordedDetections(const Path &manifest, const Path &jsonl) {
  require(std::filesystem::file_size(jsonl) <= 128*1024*1024, "cache too large");
  auto input = Json::parse(readText(manifest));
  auto receiptPath = jsonl.parent_path()/"acceptance.json";
  auto receipt = Json::parse(readText(receiptPath));
  auto video = input.at("provenance").at("video_sha256").get<std::string>();
  require(video.size() == 64 && receipt.at("video_sha256") == video,
          "cache receipt/video SHA256 mismatch");
  std::map<uint64_t, Json> entries;
  for (auto &f : input.at("frames")) {
    auto id = f.at("pair_id").get<uint64_t>();
    require(entries.emplace(id,f).second, "duplicate input pair");
    auto path = utf8Path(f.at("file").get<std::string>());
    require(fileSha256(manifest.parent_path()/path) == f.at("sha256"),
            "input packet SHA256 mismatch");
  }
  std::set<std::pair<uint64_t,int>> seen;
  std::istringstream stream(readText(jsonl));
  for (std::string line; std::getline(stream,line);) {
    if (line.empty()) continue;
    auto j = Json::parse(line);
    auto meta = parseMeta(j);
    auto found = entries.find(meta.pair_id);
    require(found != entries.end(), "cache pair absent from input");
    auto eye = j.at("eye").get<std::string>();
    require(eye == "left" || eye == "right", "wrong eye");
    int e = eye == "left" ? 0 : 1;
    require(seen.emplace(meta.pair_id,e).second, "duplicate cache pair/eye");
    require(j.at("source_pair_id") == meta.pair_id, "source pair mismatch");
    for (auto key : {"timestamp_ns","eye_timestamp_ns","camera_frame_id",
                     "config_version","calibration_version","source","time_source"})
      require(j.at(key) == found->second.at(key), std::string("source mismatch: ")+key);
    const auto backend = j.at("backend").get<std::string>();
    require((backend == "actual-model" || backend == "actual-model-c-actual-v2" ||
             backend == "actual-model-c-actual-v2.4-unified" ||
             backend == "actual-model-c-actual-v2.4-unified-all") && j.at("status") == "ok",
            "expected successful actual-model record");
    require(j.at("diagnostics").at("model_sha256") == receipt.at("model_sha256"),
            "model hash mismatch");
    std::string expectedVersion;
    if (backend == "actual-model" && !j.at("diagnostics").contains("detector_mode")) {
      expectedVersion = std::string("C_ACTUAL_INTERFACE_V2_1:") +
        receipt.at("model_sha256").at("ball").get<std::string>() + ":" +
        receipt.at("model_sha256").at("hand").get<std::string>() + ":" +
        receipt.at("model_sha256").at("racket").get<std::string>();
    } else {
      const auto version = j.at("diagnostics").at("interface_version").get<std::string>();
      const auto mode = j.at("diagnostics").at("detector_mode").get<std::string>();
      require(version == "C_ACTUAL_INTERFACE_V2_1" || version == "C_ACTUAL_INTERFACE_V2_3" ||
              version == "C_ACTUAL_INTERFACE_V2_4" ||
              version == "C_ACTUAL_INTERFACE_V2_4_UNIFIED_ALL_1", "unsupported C interface");
      const bool v6=mode=="v6_ball_unified_hand_racket";
      const bool all=mode=="unified_all" || v6;
      require(all == (version=="C_ACTUAL_INTERFACE_V2_4_UNIFIED_ALL_1"), "local YOLO ball interface mismatch");
      require(mode == "split" || (mode == "unified" && version == "C_ACTUAL_INTERFACE_V2_4") || all,
              "unsupported C detector mode");
      require((mode == "unified") == (backend == "actual-model-c-actual-v2.4-unified"),
              "backend/detector mode mismatch");
      require(all == (backend == "actual-model-c-actual-v2.4-unified-all"), "all-class backend mismatch");
      const auto &hashes = receipt.at("model_sha256");
      require(all ? (hashes.contains("unified") && hashes.size()==size_t(v6?2:1) && (!v6 || hashes.contains("v6_ball"))) :
              hashes.contains("ball") && (mode == "unified" ? hashes.contains("unified")
              : (hashes.contains("hand") && hashes.contains("racket"))), "incomplete model identities");
      if(all) for(const auto &box:j.at("boxes"))
        require(box.at("bbox_semantics")=="detector_box" && !box.contains("center"),
                "single-YOLO box falsely declares a measured center");
      expectedVersion = version + ":" + mode + ":" + hashes.dump();
      if(j.at("diagnostics").contains("diagnostic_thresholds"))
        expectedVersion += ":thresholds:"+j.at("diagnostics").at("diagnostic_thresholds").dump();
      if(v6) expectedVersion += ":v6_conf="+std::to_string(j.at("diagnostics").at("yolo_ball_conf").get<float>());

    }
    require(meta.model_version == expectedVersion, "model version mismatch");
    boxes(j.at("boxes"));
    DetectionResult r;
    r.meta=meta; r.eye=static_cast<Eye>(e); r.backend="actual_model_record_replay";
    r.boxes=j.at("boxes"); r.diagnostics=j.at("diagnostics");
    r.diagnostics["recorded_backend"]=backend;
    r.reference_id=j.at("reference_id").get<std::array<uint64_t,2>>();
    r.reference_timestamp_ns=j.at("reference_timestamp_ns").get<std::array<int64_t,2>>();
    r.reference_valid=j.at("reference_valid").get<std::array<bool,2>>();
    r.task_id=j.value("task_id",uint64_t(0));
    records_[meta.pair_id][e]=std::move(r);
  }
  require(seen.size() == entries.size()*2, "incomplete eye coverage");
  provenance_={{"mode","actual_model_record_replay"},{"video_sha256",video},
    {"cache_sha256",fileSha256(jsonl)},{"receipt_sha256",fileSha256(receiptPath)},
    {"model_sha256",receipt.at("model_sha256")},{"pairs",entries.size()}};
}
std::vector<DetectionResult> RecordedDetections::frame(const FramePair &f, const MotionResult &m) const {
  auto it=records_.find(f.meta.pair_id);
  require(it != records_.end(), "frame absent from cache");
  std::vector<DetectionResult> out;
  for (int e=0;e<2;++e) {
    auto r=it->second[e];
    auto a=metaJson(r.meta), b=metaJson(f.meta);
    a.erase("model_version"); b.erase("model_version");
    require(a==b, "runtime frame metadata mismatch");
    for (int k=0;k<2;++k)
      require(r.reference_id[k] == m.eyes[k].reference_id &&
              r.reference_valid[k] == m.eyes[k].reference_valid &&
              r.reference_timestamp_ns[k] == m.eyes[k].reference_timestamp_ns,
              "runtime reference mismatch");
    out.push_back(std::move(r));
  }
  return out;
}
} // namespace pipeline
