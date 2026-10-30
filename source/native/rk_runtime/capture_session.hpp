#pragma once
#include "pipeline/pipeline.hpp"
#include <fstream>
#include <csignal>

namespace field_capture {
using namespace pipeline;
// A valid flight already brackets its apex with actual observations. Keep a
// short tail for delayed NPU updates, then close the producer queues normally.
class FitStop {
 public:
  bool enabled=false;
  Json event=nullptr;
  uint64_t reported_pair=0;
  void observe(const Json &measurement,uint64_t pair) {
    const Json *e=nullptr;
    if(measurement.contains("events") && valid(measurement["events"])) e=&measurement["events"];
    if(measurement.contains("latest_valid_flight") && measurement["latest_valid_flight"].is_object()) {
      const auto &last=measurement["latest_valid_flight"];
      if(last.contains("event") && valid(last["event"])) e=&last["event"];
    }
    if(!e) return;
    event=*e; reported_pair=pair;
    if(!first_) first_=Clock::now();
  }
  bool due() const { return enabled && first_ && Clock::now()-*first_>=std::chrono::milliseconds(350); }
  static bool valid(const Json &e) {
    if(!e.is_object() || !e.value("fit_valid",false) || e.value("status","")=="cancelled") return false;
    for(auto key:{"release_world_m","apex_world_m"}) {
      if(!e.contains(key) || !e[key].is_array() || e[key].size()!=3) return false;
      for(const auto &v:e[key]) if(!v.is_number() || !std::isfinite(v.get<double>())) return false;
    }
    return e["apex_world_m"][2].get<double>()>e["release_world_m"][2].get<double>();
  }
 private:
  std::optional<Clock::time_point> first_;
};

class MjpegArchive {
 public:
  explicit MjpegArchive(Path output):root_(std::move(output)) {
    std::filesystem::create_directories(root_/"input/jpeg");
    index_.open(root_/"input/capture-index.jsonl");
    if(!index_) throw std::runtime_error("Cannot create capture index");
  }
  void append(const Meta &meta,const std::vector<uint8_t> &jpeg) {
    const auto relative="jpeg/"+std::to_string(meta.pair_id)+".jpg";
    writeBytes(root_/"input"/relative,jpeg);
    Json entry=metaJson(meta);
    entry.update({{"format","MJPG"},{"width",2560},{"height",720},{"file",relative},{"sha256",sha256(jpeg)}});
    entries_.push_back(entry); index_<<entry.dump()<<'\n'; index_.flush();
    if(!index_) throw std::runtime_error("Cannot write capture index");
  }
  size_t size() const { return entries_.size(); }
  void finish() {
    if(done_) return;
    writeText(root_/"input/manifest.json",Json{{"schema_version",1},{"mode","file"},{"frames",entries_},
      {"provenance",{{"source","uvc-original-mjpg-packets"},{"fps",60},{"sampling_time","original V4L2 timestamps"}}}}.dump(2));
    index_.close(); done_=true;
  }
  ~MjpegArchive() { try { finish(); } catch(...) {} }
 private:
  Path root_; std::ofstream index_; Json entries_=Json::array(); bool done_=false;
};
inline volatile std::sig_atomic_t interrupted=0;
inline void interrupt(int) { interrupted=1; }
}
