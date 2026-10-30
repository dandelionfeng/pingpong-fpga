#pragma once
#include "pipeline/pipeline.hpp"
#include <opencv2/imgproc.hpp>
#include <cmath>
#include <cstdlib>
namespace field_preprocess {
using namespace pipeline;
inline cv::Mat clean(const cv::Mat&raw){auto m=binaryMorph(raw,false);m=binaryMorph(m,true);m=binaryMorph(m,true);return binaryMorph(m,false);}
inline cv::Mat reference(const cv::Mat&g,const cv::Mat&diff,const cv::Mat&previous,int mode){
 cv::Mat raw,pos,weak,strong;cv::compare(diff,12,raw,cv::CMP_GT);cv::compare(diff,6,weak,cv::CMP_GT);cv::compare(diff,18,strong,cv::CMP_GT);
 if(previous.empty())pos=cv::Mat::zeros(g.size(),CV_8U);else {cv::compare(g,previous,pos,cv::CMP_GT);cv::bitwise_and(pos,raw,pos);}
 if(mode==0)return clean(raw);if(mode==1)return clean(pos);
 if(mode==2){for(int i=0;i<4;++i){strong=binaryMorph(strong,true);cv::bitwise_and(strong,weak,strong);}return strong;}
 if(mode==4){auto out=clean(raw);cv::bitwise_or(out,pos,out);return out;}
 cv::Mat dx,dy,energy,edge;cv::Sobel(g,dx,CV_32F,1,0,3,1,0,cv::BORDER_REPLICATE);cv::Sobel(g,dy,CV_32F,0,1,3,1,0,cv::BORDER_REPLICATE);
 energy=dx.mul(dx)+dy.mul(dy);cv::compare(energy,1024,edge,cv::CMP_GT);cv::bitwise_and(edge,weak,edge);auto out=clean(edge);cv::bitwise_or(out,pos,out);return out;
}
class Inline {
 std::string mode_;std::array<cv::Mat,2> previous_,background_,variance_;size_t calls_=0,eligible_=0;Json last_=Json::object();
 struct Hint {uint64_t id=0;int64_t ns=0;cv::Rect2d box;};
 std::array<std::optional<Hint>,2> balls_,hands_;
 static cv::Rect clipped(cv::Rect r,cv::Size size){return r&cv::Rect(0,0,size.width,size.height);}
public:
 Inline(){mode_=std::getenv("CHAIN_INLINE_PREPROCESS")?std::getenv("CHAIN_INLINE_PREPROCESS"):"none";
  if(mode_!="none"&&mode_!="reconstruction"&&mode_!="tophat"&&mode_!="watershed"&&mode_!="cca"&&mode_!="sigma_delta")throw std::runtime_error("Unknown inline preprocessor");}
 void accept(const std::vector<DetectionResult>&ds){
  for(const auto&d:ds)if(d.status=="ok"){
   int e=int(d.eye);std::optional<Hint> ball,hand;double bc=-1,hc=-1;
   for(const auto&b:d.boxes){auto v=b.at("bbox").get<std::vector<double>>();if(v.size()!=4)continue;const auto cls=b.value("class",std::string());double conf=b.value("confidence",0.);
    if(cls=="ball"&&conf>bc){bc=conf;ball=Hint{d.meta.pair_id,d.meta.timestamp_ns,{v[0]/2,v[1]/2,v[2]/2,v[3]/2}};}
    if(cls=="hand"&&conf>hc){hc=conf;hand=Hint{d.meta.pair_id,d.meta.timestamp_ns,{v[0]/2,v[1]/2,v[2]/2,v[3]/2}};}}
   if(ball)balls_[e]=ball;if(hand)hands_[e]=hand;
  }
 }
 void apply(const FramePair&f,MotionResult&m){
  last_=Json::object();if(mode_=="none")return;++calls_;
  for(int e=0;e<2;++e){
   auto g=integerGaussian(f.search[e]);cv::Mat diff=cv::Mat::zeros(g.size(),CV_8U),weak,strong,out=m.eyes[e].stages[6].clone();
   if(!previous_[e].empty())cv::absdiff(g,previous_[e],diff);
   cv::compare(diff,6,weak,cv::CMP_GT);cv::compare(diff,18,strong,cv::CMP_GT);
   if(mode_=="sigma_delta"){
    if(background_[e].empty()){background_[e]=g.clone();variance_[e]=cv::Mat(g.size(),CV_8U,cv::Scalar(2));out=cv::Mat::zeros(g.size(),CV_8U);}
    else {
     cv::Mat plus,minus,delta,target;cv::compare(g,background_[e],plus,cv::CMP_GT);cv::compare(g,background_[e],minus,cv::CMP_LT);
     cv::add(background_[e],cv::Scalar(1),background_[e],plus);cv::subtract(background_[e],cv::Scalar(1),background_[e],minus);
     cv::absdiff(g,background_[e],delta);delta.convertTo(target,CV_8U,4.);
     cv::compare(target,variance_[e],plus,cv::CMP_GT);cv::compare(target,variance_[e],minus,cv::CMP_LT);
     cv::add(variance_[e],cv::Scalar(1),variance_[e],plus);cv::subtract(variance_[e],cv::Scalar(1),variance_[e],minus);cv::max(variance_[e],2,variance_[e]);
     cv::compare(delta,variance_[e],out,cv::CMP_GE);out=clean(out);
    }
   }else if(mode_=="reconstruction"){
    cv::Mat labels;int n=cv::connectedComponents(weak,labels,8);std::vector<uint8_t> keep(n);
    for(int y=0;y<g.rows;++y)for(int x=0;x<g.cols;++x)if(strong.at<uint8_t>(y,x))keep[labels.at<int>(y,x)]=255;keep[0]=0;
    for(int y=0;y<g.rows;++y)for(int x=0;x<g.cols;++x)out.at<uint8_t>(y,x)=keep[labels.at<int>(y,x)];
   }else if(mode_=="tophat"){
    cv::Mat top=cv::Mat::zeros(g.size(),CV_8U);
    for(int k:{9,13,17}){cv::Mat one;cv::morphologyEx(g,one,cv::MORPH_TOPHAT,cv::Mat::ones(k,k,CV_8U),cv::Point(-1,-1),1,cv::BORDER_REPLICATE);cv::max(top,one,top);}
    cv::Mat selected;cv::compare(top,12,selected,cv::CMP_GT);cv::bitwise_and(selected,binaryMorph(weak,true),selected);cv::bitwise_or(out,selected,out);
   }else if(mode_=="cca"){
    cv::Mat labels,stats,centres;int n=cv::connectedComponentsWithStats(out,labels,stats,centres,8);std::vector<uint8_t> keep(n);
    for(int i=1;i<n;++i)if(stats.at<int>(i,cv::CC_STAT_AREA)>=3)keep[i]=255;
    for(int y=0;y<g.rows;++y)for(int x=0;x<g.cols;++x)out.at<uint8_t>(y,x)=keep[labels.at<int>(y,x)];last_[std::to_string(e)+"_components"]=n-1;
   }else if(mode_=="watershed"&&balls_[e]&&hands_[e]&&f.meta.timestamp_ns>=balls_[e]->ns&&f.meta.timestamp_ns-balls_[e]->ns<=250000000&&f.meta.timestamp_ns-hands_[e]->ns<=500000000){
    auto b=balls_[e]->box,h=hands_[e]->box;auto bc=cv::Point(int(b.x+b.width/2),int(b.y+b.height/2));
    auto roi=clipped((cv::Rect(h)|cv::Rect(b))+cv::Size(16,16)-cv::Point(8,8),g.size());
    if(!roi.empty()&&roi.width<=200&&roi.height<=200&&roi.contains(bc)){
     cv::Mat patch=g(roi),binary,markers=cv::Mat::ones(roi.size(),CV_32S),colour;
     cv::threshold(patch,binary,0,255,cv::THRESH_BINARY_INV|cv::THRESH_OTSU);cv::erode(binary,binary,cv::Mat::ones(3,3,CV_8U));
     cv::Mat unknown=cv::Mat::zeros(roi.size(),CV_8U);cv::rectangle(unknown,clipped(cv::Rect(2,2,roi.width-4,roi.height-4),roi.size()),cv::Scalar(255),-1);markers.setTo(0,unknown);markers.setTo(2,binary);
     cv::circle(markers,bc-roi.tl(),2,cv::Scalar(3),-1);cv::cvtColor(patch,colour,cv::COLOR_GRAY2BGR);cv::watershed(colour,markers);
     cv::Mat target=out(roi);target.setTo(0,markers==-1);++eligible_;
     last_[std::to_string(e)+"_marker_source"]={{"ball_pair_id",balls_[e]->id},{"hand_pair_id",hands_[e]->id},{"source","recent_semantic_ROI_current_gray"}};
    }
   }
   previous_[e]=g;m.eyes[e].stages[6]=out;
  }
  m.backend+="+inline-"+mode_;
 }
 Json configuration()const{return {{"mode",mode_},{"execution","main_thread_before_TESO_and_B"},{"calls",calls_},{"watershed_eyes",eligible_},
   {"parameters",{{"weak",6},{"strong",18},{"tophat_sizes",{9,13,17}},{"tophat_threshold",12},{"min_area",3},{"sigma_delta_scale",4},{"sigma_delta_min_variance",2}}},{"latest",last_}};}
 bool enabled()const{return mode_!="none";}
};
}
