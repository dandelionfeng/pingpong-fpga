#pragma once
#include "pipeline/pipeline.hpp"
#include "trajectory.hpp"
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <cmath>
#include <deque>

namespace pipeline {
// No semantic model is trained or replaced. Predictions locate a search ROI;
// every distance below is measured again from its own original source image.
class MaskRelease {
public:
  struct Proposal { pingpong::trajectory::TimeInterval interval; Json evidence; };
  void clear(){cache_.clear();proposal_.reset();last_=Json::object();}
  void observe(const FramePair& f,const MotionResult& m,const std::vector<DetectionResult>& records,
      const std::optional<pingpong::trajectory::WorldObservation>& obs,const std::string& calibration) {
    if(!m.valid || m.meta.pair_id!=f.meta.pair_id || m.meta.timestamp_ns!=f.meta.timestamp_ns)return;
    if(!cache_.empty()&&cache_.back().calibration!=calibration)clear();
    cache_.erase(std::remove_if(cache_.begin(),cache_.end(),[&](const Sample&s){return s.meta.pair_id==f.meta.pair_id;}),cache_.end());
    Sample s;s.meta=f.meta;s.original=f.original;s.motion=m;s.records=records;s.obs=obs;s.calibration=calibration;cache_.push_back(std::move(s));
    std::sort(cache_.begin(),cache_.end(),[](const Sample&a,const Sample&b){return a.meta.timestamp_ns<b.meta.timestamp_ns;});
    while(cache_.size()>8)cache_.pop_front();
  }
  std::optional<Proposal> estimate(pingpong::trajectory::TimeInterval coarse) {
    if(proposal_)return proposal_;
    last_={{"accepted",false},{"reason","insufficient_source_pixels"}};
    const Sample *a=nullptr,*b=nullptr;
    for(const auto&s:cache_){if(s.meta.timestamp_ns==coarse.begin_ns)a=&s;if(s.meta.timestamp_ns==coarse.end_ns)b=&s;}
    if(!a||!b||!a->obs||!b->obs||b->meta.timestamp_ns<=a->meta.timestamp_ns)return std::nullopt;
    std::array<Blob,2> seedA,seedB;std::array<double,2> radius;
    for(int eye=0;eye<2;++eye){
      const auto pa=eye?a->obs->right:a->obs->left,pb=eye?b->obs->right:b->obs->left;
      radius[eye]=nominalRadius(*a,eye,pa);
      auto ba=extractBall(a->original[eye],pa,radius[eye],12),bb=extractBall(b->original[eye],pb,radius[eye],12);
      if(!ba||!bb)return std::nullopt;seedA[eye]=*ba;seedB[eye]=*bb;
    }
    std::vector<Distance> values;Json pixels=Json::array();
    for(const auto&s:cache_){
      if(s.meta.timestamp_ns>b->meta.timestamp_ns||s.meta.timestamp_ns<a->meta.timestamp_ns-120000000)continue;
      Distance d;d.id=s.meta.pair_id;d.ns=s.meta.timestamp_ns;Json eyes=Json::array();bool valid=true;
      for(int eye=0;eye<2;++eye){
        const double t=double(s.meta.timestamp_ns-a->meta.timestamp_ns)/double(b->meta.timestamp_ns-a->meta.timestamp_ns);
        const auto pred=seedA[eye].center+(seedB[eye].center-seedA[eye].center)*t;
        const double minArea=.3*std::min(seedA[eye].area,seedB[eye].area);
        auto blob=extractBall(s.original[eye],pred,radius[eye],std::max(12.,minArea));
        if(!blob){valid=false;break;}
        auto gap=measureHand(s,eye,*blob,radius[eye]);if(!gap){valid=false;break;}
        d.gap[eye]=gap->gap/radius[eye];
        eyes.push_back({{"eye",eye?"right":"left"},{"ball_center_px",{blob->center.x,blob->center.y}},
          {"ball_core_area_px",blob->area},{"nominal_radius_px",radius[eye]},{"ball_hand_gap_px",gap->gap},
          {"hand_threshold",gap->threshold},{"hand_motion_overlap_px",gap->overlap},
          {"hand_roi",{gap->box.x,gap->box.y,gap->box.width,gap->box.height}}});
      }
      if(valid){d.value=std::min(d.gap[0],d.gap[1]);values.push_back(d);pixels.push_back({{"pair_id",d.id},{"timestamp_ns",d.ns},{"normalized_gap",d.value},{"eyes",eyes}});}
    }
    last_["samples"]=pixels;
    if(values.size()<5){last_["reason"]="insufficient_binocular_distance_samples";return std::nullopt;}
    auto fit=changePoint(values);if(!fit){last_["reason"]="distance_change_not_supported";return std::nullopt;}
    Proposal p;p.interval={fit->lo,fit->hi};
    p.evidence={{"accepted",true},{"method","mask_gray_distance_changepoint_v1"},{"samples",pixels},
      {"seed_pair_ids",{a->meta.pair_id,b->meta.pair_id}},{"confirmed_at_pair_id",cache_.back().meta.pair_id},
      {"changepoint_estimate_ns",fit->ns},{"distance_fit_rms_radii",fit->rms},
      {"straight_line_error_reduction",fit->improvement},{"calibration_sha256",a->calibration},
      {"source","same_frame_gray_and_motion_mask"},{"truth_loaded",false},{"cache_pairs",8}};
    proposal_=p;last_=p.evidence;return proposal_;
  }
  Json diagnostics()const{return last_;}
  // Recent semantic boxes locate search regions only. Every ball and hand
  // distance is measured again on the current gray image and FPGA Mask.
  // This gate schedules the hand graph; it never replaces the final event fit.
  void acceptGateHints(const std::vector<DetectionResult>& records) {
    for(const auto&r:records)if(r.status=="ok") {
      const int e=int(r.eye);if(e<0||e>1)continue;
      for(const auto&b:r.boxes) {
        const auto cls=b.value("class",std::string());
        const auto v=b.at("bbox").get<std::vector<double>>();if(v.size()!=4)continue;
        if(cls=="hand" && b.value("confidence",0.)>=.10) {
          if(handHint_[e].empty()||handHint_[e].front().ns!=r.meta.timestamp_ns)handHint_[e].clear();
          handHint_[e].push_back({r.meta.pair_id,r.meta.timestamp_ns,{v[0],v[1],v[2],v[3]},b.value("confidence",0.)});
        }
      }
      std::optional<Hint> best;double score=-1e9;
      for(const auto&b:r.boxes)if(b.value("class",std::string())=="ball") {
        const auto v=b.at("bbox").get<std::vector<double>>();if(v.size()!=4)continue;
        cv::Rect2d box(v[0],v[1],v[2],v[3]);const auto center=cv::Point2d(box.x+box.width/2,box.y+box.height/2);
        double s=b.value("confidence",0.);
        if(!ballHint_[e].empty()) {const auto&p=ballHint_[e].back().box;s-=cv::norm(center-cv::Point2d(p.x+p.width/2,p.y+p.height/2))/100.;}
        else if(!handHint_[e].empty()){double d=1e9;for(const auto&h:handHint_[e])d=std::min(d,cv::norm(center-cv::Point2d(h.box.x+h.box.width/2,h.box.y+h.box.height/2)));s-=d/100.;}
        if(s>score){score=s;best=Hint{r.meta.pair_id,r.meta.timestamp_ns,box,b.value("confidence",0.)};}
      }
      if(best && (ballHint_[e].empty()||best->ns>ballHint_[e].back().ns)) {
        ballHint_[e].push_back(*best);while(ballHint_[e].size()>2)ballHint_[e].pop_front();
      }
    }
  }
  Json updateGate(const FramePair&f,const MotionResult&m) {
    if(gateAccepted_)return *gateAccepted_;
    Json info={{"accepted",false},{"reason","waiting_for_fresh_roi_hints"}};
    Distance d;d.id=f.meta.pair_id;d.ns=f.meta.timestamp_ns;Json eyes=Json::array();
    for(int e=0;e<2;++e) {
      if(ballHint_[e].empty()||handHint_[e].empty())return info;
      const auto &h=ballHint_[e].back();const auto age=f.meta.timestamp_ns-h.ns;
      const auto handAge=f.meta.timestamp_ns-handHint_[e].front().ns;
      if(age<0||age>500000000||handAge<0||handAge>500000000)return info;
      auto center=[](const Hint&v){return cv::Point2d(v.box.x+v.box.width/2,v.box.y+v.box.height/2);};
      auto pred=center(h);
      if(ballHint_[e].size()==2){const auto&a=ballHint_[e].front();if(h.ns>a.ns)pred+=(center(h)-center(a))*double(age)/double(h.ns-a.ns);}
      const double radius=std::clamp(std::min(h.box.width,h.box.height)/2.,3.,20.);
      auto ball=extractBall(f.original[e],pred,radius,12.);
      if(!ball){info["reason"]="current_gray_ball_not_found";return info;}
      double best=1e9;std::optional<cv::Rect2d> box;uint64_t handId=0;
      for(const auto&v:handHint_[e]){double dist=cv::norm(ball->center-center(v));if(dist<best){best=dist;box=v.box;handId=v.id;}}
      Sample s;s.meta=f.meta;s.original=f.original;s.motion=m;
      auto gap=measureHandBox(s,e,*ball,radius,box,best);
      if(!gap){info["reason"]="current_mask_hand_not_found";return info;}
      d.gap[e]=gap->gap/radius;
      eyes.push_back({{"eye",e?"right":"left"},{"ball_roi_source_pair_id",h.id},{"hand_roi_source_pair_id",handId},
        {"ball_roi_age_ms",age/1e6},{"hand_roi_age_ms",handAge/1e6},{"ball_center_px",{ball->center.x,ball->center.y}},
        {"ball_hand_gap_px",gap->gap},{"normalized_gap",d.gap[e]},{"hand_motion_overlap_px",gap->overlap}});
    }
    d.value=std::min(d.gap[0],d.gap[1]);
    if(!gateValues_.empty() && d.ns-gateValues_.back().ns>50000000){gateValues_.clear();gatePixels_.clear();}
    gateValues_.push_back(d);gatePixels_.push_back({{"pair_id",d.id},{"timestamp_ns",d.ns},{"normalized_gap",d.value},{"eyes",eyes}});
    while(gateValues_.size()>8){gateValues_.erase(gateValues_.begin());gatePixels_.erase(gatePixels_.begin());}
    info["reason"]="distance_change_not_supported";info["samples"]=gatePixels_;
    if(gateValues_.size()>=5)if(auto fit=changePoint(gateValues_)) {
      info["accepted"]=true;info["reason"]="mask_gray_distance_changepoint";
      info["confirmed_at_pair_id"]=d.id;info["confirmed_at_source_time_ns"]=d.ns;
      info["release_interval"]={{"begin_ns",fit->lo},{"end_ns",fit->hi}};
      info["distance_fit_rms_radii"]=fit->rms;info["straight_line_error_reduction"]=fit->improvement;
      info["source"]="current_gray_and_fpga_mask_recent_semantic_roi";info["truth_loaded"]=false;
      gateAccepted_=info;
    }
    return info;
  }
private:
  struct Hint {uint64_t id;int64_t ns;cv::Rect2d box;double confidence;};
  struct Sample {Meta meta;std::array<cv::Mat,2> original;MotionResult motion;std::vector<DetectionResult> records;
    std::optional<pingpong::trajectory::WorldObservation> obs;std::string calibration;};
  struct Blob {cv::Point2d center;double area;cv::Rect rect;cv::Mat mask;};
  struct Gap {double gap,threshold;int overlap;cv::Rect box;};
  struct Distance {uint64_t id;int64_t ns;std::array<double,2> gap;double value;};
  struct Fit {int64_t ns,lo,hi;double rms,improvement;};
  std::array<std::deque<Hint>,2> ballHint_;
  std::array<std::vector<Hint>,2> handHint_;
  std::vector<Distance> gateValues_;
  Json gatePixels_=Json::array();std::optional<Json> gateAccepted_;
  std::deque<Sample> cache_;std::optional<Proposal> proposal_;Json last_=Json::object();
  static double nominalRadius(const Sample&s,int eye,cv::Point2d point){
    double best=1e9,radius=8;
    for(const auto&r:s.records)if(int(r.eye)==eye&&r.status=="ok"&&r.meta.pair_id==s.meta.pair_id&&r.meta.timestamp_ns==s.meta.timestamp_ns)
      for(const auto&box:r.boxes)if(box.value("class",std::string())=="ball"){
        const auto v=box.at("bbox").get<std::vector<double>>();if(v.size()!=4)continue;
        const double d=cv::norm(cv::Point2d(v[0]+v[2]/2,v[1]+v[3]/2)-point);
        if(d<best){best=d;radius=std::clamp(std::min(v[2],v[3])/2.,3.,20.);}
      }
    return radius;
  }
  static std::optional<Blob> extractBall(const cv::Mat&gray,cv::Point2d pred,double radius,double minArea){
    if(gray.type()!=CV_8U||!std::isfinite(pred.x)||!std::isfinite(pred.y)||pred.x<0||pred.y<0||pred.x>=gray.cols||pred.y>=gray.rows)return std::nullopt;
    const int x=std::max(0,int(pred.x)-28),y=std::max(0,int(pred.y)-28);
    const cv::Rect roi(x,y,std::min(56,gray.cols-x),std::min(56,gray.rows-y));if(roi.width<16||roi.height<16)return std::nullopt;
    auto patch=gray(roi);std::vector<uint8_t> sorted;sorted.reserve(patch.total());
    for(int j=0;j<patch.rows;++j)sorted.insert(sorted.end(),patch.ptr<uint8_t>(j),patch.ptr<uint8_t>(j)+patch.cols);
    std::nth_element(sorted.begin(),sorted.begin()+sorted.size()/2,sorted.end());const double bg=sorted[sorted.size()/2];
    cv::Mat binary,labels,stats,centers;cv::threshold(patch,binary,bg+8,255,cv::THRESH_BINARY);
    const int n=cv::connectedComponentsWithStats(binary,labels,stats,centers,8);double best=1e9;std::optional<Blob> result;
    for(int i=1;i<n;++i){const int xx=stats.at<int>(i,0),yy=stats.at<int>(i,1),w=stats.at<int>(i,2),h=stats.at<int>(i,3),area=stats.at<int>(i,4);
      const cv::Point2d c(centers.at<double>(i,0)+x,centers.at<double>(i,1)+y);const double d=cv::norm(c-pred);
      if(area<minArea||area>CV_PI*std::pow(radius*1.9,2)||std::max(w,h)>std::max(14.,radius*4)||d>radius*1.7+4||!xx||!yy||xx+w==patch.cols||yy+h==patch.rows)continue;
      cv::Mat component=labels==i;const double signal=cv::mean(patch,component)[0]-bg;
      const double score=d/(radius*3)+.5*std::abs(std::log(area/(CV_PI*radius*radius)))-signal/10;
      if(score<best){best=score;result=Blob{c,double(area),roi,component};}
    }
    return result;
  }
  static std::optional<Gap> measureHand(const Sample&s,int eye,const Blob&ball,double radius){
    const auto&gray=s.original[eye];const auto&motion=s.motion.eyes[eye].stages[6];
    if(motion.empty()||!s.motion.eyes[eye].reference_valid)return std::nullopt;
    double best=1e9;std::optional<cv::Rect2d> box;
    for(const auto&r:s.records)if(int(r.eye)==eye&&r.status=="ok"&&r.meta.pair_id==s.meta.pair_id&&r.meta.timestamp_ns==s.meta.timestamp_ns)
      for(const auto&b:r.boxes)if(b.value("class",std::string())=="hand"&&b.value("confidence",0.)>=.10){
        auto v=b.at("bbox").get<std::vector<double>>();if(v.size()!=4)continue;double d=cv::norm(ball.center-cv::Point2d(v[0]+v[2]/2,v[1]+v[3]/2));
        if(d<best){best=d;box=cv::Rect2d(v[0],v[1],v[2],v[3]);}}
    return measureHandBox(s,eye,ball,radius,box,best);
  }
  static std::optional<Gap> measureHandBox(const Sample&s,int eye,const Blob&ball,double radius,
      const std::optional<cv::Rect2d>&box,double best) {
    const auto&gray=s.original[eye];const auto&motion=s.motion.eyes[eye].stages[6];
    if(motion.empty()||!s.motion.eyes[eye].reference_valid||!box||best>radius*8)return std::nullopt;
    cv::Rect hr(std::max(0,int(box->x)-8),std::max(0,int(box->y)-8),0,0);
    hr.width=std::min(gray.cols,int(std::ceil(box->x+box->width))+8)-hr.x;
    hr.height=std::min(gray.rows,int(std::ceil(box->y+box->height))+8)-hr.y;
    if(hr.empty()||hr.width>256||hr.height>256)return std::nullopt;
    cv::Mat hm,labels,stats,centers;const double threshold=cv::threshold(gray(hr),hm,0,255,cv::THRESH_BINARY_INV|cv::THRESH_OTSU);
    cv::morphologyEx(hm,hm,cv::MORPH_CLOSE,cv::Mat::ones(3,3,CV_8U));
    const int n=cv::connectedComponentsWithStats(hm,labels,stats,centers,8);int selected=0,areaBest=0,overlapBest=0;
    for(int k=1;k<n;++k){int area=stats.at<int>(k,4),overlap=0;if(area<30)continue;
      for(int y=0;y<labels.rows;++y)for(int x=0;x<labels.cols;++x)if(labels.at<int>(y,x)==k&&motion.at<uint8_t>((y+hr.y)/2,(x+hr.x)/2))++overlap;
      if(overlap>=3&&area>areaBest){selected=k;areaBest=area;overlapBest=overlap;}}
    if(!selected)return std::nullopt;
    const cv::Rect roi=hr|ball.rect;cv::Mat hand=cv::Mat::zeros(roi.size(),CV_8U);cv::Mat component=labels==selected;
    component.copyTo(hand(cv::Rect(hr.x-roi.x,hr.y-roi.y,hr.width,hr.height)));
    cv::Mat inverse,distance;cv::bitwise_not(hand,inverse);cv::distanceTransform(inverse,distance,cv::DIST_L2,cv::DIST_MASK_PRECISE);
    double gap=1e9;for(int y=0;y<ball.mask.rows;++y)for(int x=0;x<ball.mask.cols;++x)if(ball.mask.at<uint8_t>(y,x))
      gap=std::min(gap,double(distance.at<float>(y+ball.rect.y-roi.y,x+ball.rect.x-roi.x)));
    return Gap{gap,threshold,overlapBest,hr};
  }
  static std::optional<Fit> changePoint(const std::vector<Distance>& d){
    const size_t n=d.size();const double t0=d.front().ns*1e-9,lo=d[1].ns*1e-9-t0,hi=d[n-3].ns*1e-9-t0;
    double best=1e9,chosen=0,rate=0,base=0;auto solve=[&](double tau,bool hinge){
      double sx=0,sy=0,sxx=0,sxy=0;for(const auto&p:d){const double t=(p.ns-d.front().ns)*1e-9,x=hinge?std::max(0.,t-tau):t;sx+=x;sy+=p.value;sxx+=x*x;sxy+=x*p.value;}
      const double den=n*sxx-sx*sx;if(den<1e-12)return std::array<double,3>{1e9,0,0};const double v=(n*sxy-sx*sy)/den,b=(sy-v*sx)/n;double err=0;
      for(const auto&p:d){double t=(p.ns-d.front().ns)*1e-9,x=hinge?std::max(0.,t-tau):t;err+=std::pow(p.value-b-v*x,2);}return std::array<double,3>{err/n,v,b};};
    for(int i=0;i<=64;++i){const double tau=lo+(hi-lo)*i/64;auto f=solve(tau,true);if(f[1]>0&&f[2]>=0&&f[0]<best){best=f[0];chosen=tau;rate=f[1];base=f[2];}}
    (void)base;auto line=solve(0,false);const double reduction=1-best/std::max(1e-12,line[0]);
    if(best>=1e8||std::sqrt(best)>.4||reduction<.25||rate*((d.back().ns-d.front().ns)*1e-9-chosen)<1.)return std::nullopt;
    const int64_t ns=d.front().ns+int64_t(std::llround(chosen*1e9));
    for(size_t i=1;i<n;++i)if(d[i-1].ns<=ns&&ns<=d[i].ns&&d[i].ns-d[i-1].ns<=50000000)
      return Fit{ns,d[i-1].ns,d[i].ns,std::sqrt(best),reduction};
    return std::nullopt;
  }
};
} // namespace pipeline
