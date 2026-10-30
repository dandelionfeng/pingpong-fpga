#pragma once
#include "pipeline/pipeline.hpp"
#include "runtime_session.hpp"
#include <opencv2/imgproc.hpp>
#include <cmath>
// Temporary two-graph comparison: selected ball specialist + existing unified
// hand/racket graph. This does not claim C has retrained a new unified model.
class SelectedBallDetector final : public pipeline::DetectorBackend {
 std::unique_ptr<pipeline::DetectorBackend> semantics_;
 c_actual::OrtSession ball_;std::string model_,model_hash_;int side_=0;
public:
 SelectedBallDetector(std::unique_ptr<pipeline::DetectorBackend> semantics,const std::string &model):semantics_(std::move(semantics)),model_(model){
  model_hash_=pipeline::fileSha256(pipeline::utf8Path(model));
  std::string error;if(!ball_.load(model,false,1,&error))throw std::runtime_error(error);
  auto shape=ball_.inputShape();if(shape.size()!=4||shape[0]!=1||shape[1]!=3||shape[2]!=shape[3])throw std::runtime_error("Selected ball input shape");
  side_=int(shape[2]);auto output=ball_.outputShape();if(output.size()!=3||output[1]!=5)throw std::runtime_error("Selected ball is not a single-class detector");
 }
 pipeline::DetectionResult infer(const pipeline::DetectorContext &c,const std::atomic<bool>&stop,int timeoutMs)override{
  using namespace pipeline;auto begin=Clock::now();auto result=semantics_->infer(c,stop,timeoutMs);
  if(result.status!="ok")return result;
  const auto source=c.gray;double scale=std::min(double(side_)/source.cols,double(side_)/source.rows);
  int nw=int(std::round(source.cols*scale)),nh=int(std::round(source.rows*scale));int px=(side_-nw)/2,py=(side_-nh)/2;
  cv::Mat resized,canvas(side_,side_,CV_8UC1,cv::Scalar(114));cv::resize(source,resized,cv::Size(nw,nh),0,0,cv::INTER_LINEAR);
  resized.copyTo(canvas(cv::Rect(px,py,nw,nh)));size_t plane=size_t(side_)*side_;
  std::vector<float> input(3*plane),output;std::vector<int64_t> shape;
  for(size_t i=0;i<plane;++i)input[i]=input[plane+i]=input[2*plane+i]=canvas.data[i]/255.f;
  c_actual::resetRuntimeTimings();
  std::string error;if(!ball_.run(input,ball_.inputShape(),&output,&shape,&error))throw std::runtime_error(error);
  result.diagnostics["selected_ball_graph_ms"]=c_actual::lastRuntimeTimings();
  size_t anchors=shape[2];struct Box{cv::Rect2f bounds;float score;};std::vector<Box> candidates,kept;
  for(size_t i=0;i<anchors;++i){float score=output[4*anchors+i];if(score<.10f)continue;
   float cx=output[i],cy=output[anchors+i],w=output[2*anchors+i],h=output[3*anchors+i];
   float x1=std::clamp(float((cx-w*.5f-px)/scale),0.f,float(source.cols));float y1=std::clamp(float((cy-h*.5f-py)/scale),0.f,float(source.rows));
   float x2=std::clamp(float((cx+w*.5f-px)/scale),0.f,float(source.cols));float y2=std::clamp(float((cy+h*.5f-py)/scale),0.f,float(source.rows));
   if(x2-x1>=1 && y2-y1>=1)candidates.push_back({{x1,y1,x2-x1,y2-y1},score});
  }
  std::sort(candidates.begin(),candidates.end(),[](const Box&a,const Box&b){return a.score>b.score;});
  if(candidates.size()>300)candidates.resize(300);
  for(const auto &b:candidates){bool reject=false;for(const auto &k:kept){float area=(b.bounds&k.bounds).area();if(area/(b.bounds.area()+k.bounds.area()-area)>.5f){reject=true;break;}}
   if(!reject){kept.push_back(b);if(kept.size()==30)break;}}
  Json boxes=Json::array();for(const auto &b:result.boxes)if(b.value("class","")!="ball")boxes.push_back(b);
  for(const auto &b:kept)boxes.push_back({{"class","ball"},{"confidence",b.score},{"bbox",{b.bounds.x,b.bounds.y,b.bounds.width,b.bounds.height}},
    {"bbox_semantics","detector_box"},{"observation","observed"},{"model",model_}});
  result.boxes=std::move(boxes);result.backend="actual-rknn-selected-ball-plus-existing-unified-hands-racket";
  result.diagnostics["ball_source"]="selected_single_class_YOLO";result.diagnostics["selected_ball_model"]=model_;
  result.diagnostics["model_sha256"]["selected_ball"]=model_hash_;
  result.diagnostics["interface_version"]="C_SELECTED_BALL_PLUS_UNIFIED_1";
  result.diagnostics["detector_mode"]="selected_ball_plus_unified_hand_racket";
  result.diagnostics["active_graphs_per_eye"]=2;
  result.diagnostics["ball_detected"]=!kept.empty();
  result.diagnostics["ball_state"]=kept.empty()?"DROPOUT":"DETECTED";
  result.meta.model_version="C_SELECTED_BALL_PLUS_UNIFIED_1:"+result.diagnostics["model_sha256"].dump();
  result.diagnostics["unified_ball_output_used"]=false;result.diagnostics["graph_count_per_eye"]=2;
  double elapsed=std::chrono::duration<double,std::milli>(Clock::now()-begin).count();result.diagnostics["infer_ms"]=elapsed;
  result.completed_ns=monotonicNs();
  if(stop||elapsed>timeoutMs){result.status=stop?"cancelled":"expired";result.boxes=Json::array();}
  return result;
 }
 std::string mode()const override{return "selected-ball-plus-existing-unified-hands-racket";}
};
