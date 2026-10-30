#include "pipeline/pipeline.hpp"
#include "mask_release.hpp"
#include <fstream>
#include <iostream>
#include <numeric>
using namespace pipeline;
double elapsed(Clock::time_point t){return std::chrono::duration<double,std::milli>(Clock::now()-t).count();}
Json stats(std::vector<double> v){if(v.empty())return {{"count",0}};std::sort(v.begin(),v.end());return {{"count",v.size()},
  {"mean_ms",std::accumulate(v.begin(),v.end(),0.)/v.size()},{"p95_ms",v[size_t(.95*(v.size()-1))]},{"max_ms",v.back()}};}
int main(int argc,char**argv){try{
  if(argc!=4)throw std::runtime_error("INPUT_MANIFEST REFERENCE_CASE OUT_JSON");cv::setNumThreads(1);
  Path root=utf8Path(argv[2]);std::map<uint64_t,std::vector<DetectionResult>> records;
  std::ifstream det(root/"detections.jsonl");std::string line;
  while(std::getline(det,line)){auto j=Json::parse(line);DetectionResult r;r.meta=parseMeta(j.at("meta"));r.eye=static_cast<Eye>(j.at("eye").get<int>());r.status=j.at("status");r.boxes=j.at("boxes");records[r.meta.pair_id].push_back(std::move(r));}
  FileFrameSource input(utf8Path(argv[1]));std::ifstream rows(root/"frames.jsonl"),mask(root/"fpga-mask-sequence-lsb.bin",std::ios::binary);
  MaskRelease legacy,normal,gate;std::vector<double> observe,estimate,cold,active,stream;size_t count=0,accepted=0;Json last;
  while(std::getline(rows,line)){
    auto row=Json::parse(line);auto next=input.next();if(!next.frame)throw std::runtime_error("Source exhausted");
    auto&f=*next.frame;const auto&mrow=row.at("measurement");MotionResult m;m.meta=f.meta;m.valid=true;
    for(int e=0;e<2;++e){std::vector<uint8_t> bytes(28800);mask.read(reinterpret_cast<char*>(bytes.data()),bytes.size());if(!mask)throw std::runtime_error("Mask exhausted");
      m.eyes[e].stages[6]=unpackMask(bytes,640,360);m.eyes[e].reference_valid=row.at("reference_valid").at(e).get<bool>();}
    auto&rs=records[f.meta.pair_id];std::optional<pingpong::trajectory::WorldObservation> obs;
    if(mrow.value("semantic_ball_supported",false)&&mrow.contains("left_pixel")&&mrow.contains("right_pixel")&&!mrow["left_pixel"].is_null()&&!mrow["right_pixel"].is_null()){
      pingpong::trajectory::WorldObservation o;o.left={mrow["left_pixel"][0],mrow["left_pixel"][1]};o.right={mrow["right_pixel"][0],mrow["right_pixel"][1]};obs=o;}
    auto t=Clock::now();legacy.observe(f,m,rs,obs,"reference-calibration");observe.push_back(elapsed(t));
    normal.observe(f,m,rs,obs,"reference-calibration");
    const auto ev=mrow.value("events",Json::object());if(ev.contains("legacy_release")){
      auto j=ev["legacy_release"];pingpong::trajectory::TimeInterval coarse{j["begin_ns"],j["end_ns"]};
      auto copy=legacy;t=Clock::now();auto p=copy.estimate(coarse);double cost=elapsed(t);cold.push_back(cost);
      if(copy.diagnostics().contains("samples"))active.push_back(cost);if(p)++accepted;
      t=Clock::now();normal.estimate(coarse);estimate.push_back(elapsed(t));}
    gate.acceptGateHints(rs);t=Clock::now();last=gate.updateGate(f,m);stream.push_back(elapsed(t));++count;
  }
  Json result={{"pairs",count},{"legacy_observe",stats(observe)},{"legacy_estimate",stats(estimate)},
    {"legacy_cold_estimate",stats(cold)},{"legacy_distance_processing",stats(active)},
    {"legacy_accepted_cold_calls",accepted},{"stream_gate",stats(stream)},{"stream_gate_result",last},
    {"scope","RK CPU only; archived same-frame model results and real FPGA masks; image decode and JSON excluded from algorithm timings; full semantic frequency"}};
  writeText(utf8Path(argv[3]),result.dump(2));std::cout<<result.dump(2)<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
