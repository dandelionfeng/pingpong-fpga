#pragma once
#include "internal_onnx.hpp"
namespace pipeline {
// Three independent, already trained YOLO graphs. No synthesized boxes and no
// BallTrack warmup. This mode is an explicit accuracy candidate, not a unified
// single-pass model or a claim of 60-fps inference.
class SpecialistDetector final:public DetectorBackend {
  std::array<c_actual::YoloDetector,3> models_;
  std::array<float,3> thresholds_{};
  Json hashes_;
  std::string version_;
public:
  explicit SpecialistDetector(const Path&path){auto j=Json::parse(readText(path));c_actual::Config config;config.intra_op_threads=j.value("intra_op_threads",2);config.base_conf=.001f;
    const std::array<std::string,3> keys={"v6_ball","hand","racket"};
    for(int i=0;i<3;++i){auto item=j.at("models").at(keys[i]);auto p=utf8Path(item.at("path").get<std::string>());if(p.is_relative())p=path.parent_path()/p;auto hash=fileSha256(p);if(hash!=item.at("sha256"))throw std::runtime_error("specialist model hash mismatch");hashes_[keys[i]]=hash;thresholds_[i]=j.at("thresholds").at(keys[i]);if(!std::isfinite(thresholds_[i])||thresholds_[i]<0||thresholds_[i]>1)throw std::runtime_error("specialist threshold");std::string why;std::vector<std::string> names=i==0?std::vector<std::string>{"ball"}:i==1?std::vector<std::string>{"hand"}:std::vector<std::string>{"ball","racket"};if(!models_[i].load(pathUtf8(p),names,config,false,&why)||models_[i].numClasses()!=int(names.size()))throw std::runtime_error("specialist graph class contract: "+why);}
    version_="C_SPECIALISTS_1:"+hashes_.dump()+":"+j.at("thresholds").dump();
  }
  DetectionResult infer(const DetectorContext&c,const std::atomic<bool>&stop,int timeout)override{auto start=Clock::now();DetectionResult r;r.meta=c.meta;r.meta.model_version=version_;r.eye=c.eye;r.task_id=c.task_id;r.generation=c.generation;r.reference_id=c.reference_id;r.reference_valid=c.reference_valid;r.reference_timestamp_ns=c.reference_timestamp_ns;r.backend=mode();if(stop){r.status="cancelled";return r;}if(c.gray.type()!=CV_8UC1||c.origin!=cv::Point()||c.gray.size()!=c.original_size)throw std::runtime_error("original gray8 specialist input required");auto gray3=c_actual::preprocess::grayToGray3(c.gray);std::array<std::string,3> labels={"ball","hand","racket"};Json times=Json::array();bool ball=false;
    for(int i=0;i<3;++i){auto t=Clock::now();std::string why;auto boxes=models_[i].detect(gray3,thresholds_[i],c.gray.cols,c.gray.rows,&why);if(!why.empty())throw std::runtime_error(why);for(auto&b:boxes)if(b.class_name==labels[i]){ball|=i==0;r.boxes.push_back({{"class",b.class_name},{"confidence",b.confidence},{"bbox",{b.x,b.y,b.w,b.h}},{"bbox_semantics","detector_box"},{"observation","observed"}});}times.push_back(std::chrono::duration<double,std::milli>(Clock::now()-t).count());}
    double ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();r.completed_ns=monotonicNs();r.diagnostics={{"interface_version","C_SPECIALISTS_1"},{"model_sha256",hashes_},{"ball_state",ball?"DETECTED":"DROPOUT"},{"ball_detected",ball},{"infer_ms",ms},{"graph_ms",times},{"active_graphs_per_eye",3},{"unified_ball_output_used",false},{"hand_source","hand_v3_specialist"},{"racket_source","racket_640_specialist"},{"ball_source","V6_Round2_YOLO"}};if(stop||ms>timeout){r.status=stop?"cancelled":"expired";r.boxes=Json::array();}return r;
  }
  std::string mode()const override{return "actual-model-v6-handv3-racket-specialists";}
};
}
