#include "pipeline/pipeline.hpp"
#include <opencv2/calib3d.hpp>
#include <cstdlib>
#include <fstream>

namespace pipeline {
namespace {
struct Cal {
  cv::Mat k1,d1,k2,d2,r1,r2,p1,p2,r,t;
  bool loaded=false;
};
cv::Mat mat(const Json& j,int rows,int cols) {
  cv::Mat m(rows,cols,CV_64F);
  for(int y=0;y<rows;++y) for(int x=0;x<cols;++x) m.at<double>(y,x)=j.at(y).at(x).get<double>();
  return m;
}
Cal load() {
  const char* p=std::getenv("PIPELINE_B_CALIBRATION"); if(!p||!*p) return {};
  std::ifstream in(p); if(!in) return {};
  Json j; try { in>>j; } catch(...) { return {}; }
  try {
    Cal c; c.k1=mat(j.at("K_left"),3,3); c.k2=mat(j.at("K_right"),3,3);
    auto d1=j.at("D_left"),d2=j.at("D_right"); c.d1=cv::Mat(1,int(d1.size()),CV_64F); c.d2=cv::Mat(1,int(d2.size()),CV_64F);
    for(std::size_t i=0;i<d1.size();++i) c.d1.at<double>(0,int(i))=d1.at(i).get<double>();
    for(std::size_t i=0;i<d2.size();++i) c.d2.at<double>(0,int(i))=d2.at(i).get<double>();
    c.r1=mat(j.at("R1"),3,3); c.r2=mat(j.at("R2"),3,3); c.p1=mat(j.at("P1"),3,4); c.p2=mat(j.at("P2"),3,4);
    c.r=mat(j.at("R_left_to_right"),3,3); c.t=cv::Mat(3,1,CV_64F);
    for(int i=0;i<3;++i) c.t.at<double>(i,0)=j.at("T_m").at(i).get<double>();
    c.loaded=true; return c;
  } catch(...) { return {}; }
}
bool same(const Meta&a,const Meta&b){return a.pair_id==b.pair_id&&a.timestamp_ns==b.timestamp_ns&&a.config_version==b.config_version;}
Json point(const DetectionResult& d){
  for(const auto& b:d.boxes){ if(b.value("class","")!="ball") continue; auto q=b.at("bbox"); if(q.size()!=4) continue; double x=q[0].get<double>()+q[2].get<double>()*.5,y=q[1].get<double>()+q[3].get<double>()*.5; if(std::isfinite(x)&&std::isfinite(y)&&x>=0&&x<1280&&y>=0&&y<720) return {x,y}; }
  return nullptr;
}
}
class BMeasurement final : public MeasurementModule {
 public:
  BMeasurement():cal_(load()){}
  Json process(const FramePair& f,const MotionResult& m,const std::vector<DetectionResult>& rs) override {
    Json out={{"pair_id",f.meta.pair_id},{"timestamp_ns",f.meta.timestamp_ns},{"version",version()},{"coordinate_frame","left_camera"},{"unit","m"},{"observations",Json::array()}};
    const DetectionResult *l=nullptr,*r=nullptr; for(const auto& d:rs){if(d.meta.pair_id!=f.meta.pair_id||!same(d.meta,f.meta)||d.status!="ok") continue; if(d.eye==Eye::Left) l=&d; else r=&d;}
    if(!cal_.loaded){out["status"]="invalid";out["reason"]="calibration_unavailable";return out;}
    if(!l||!r){out["status"]="invalid";out["reason"]="same_frame_left_right_detections_missing";return out;}
    Json lp=point(*l),rp=point(*r); if(lp.is_null()||rp.is_null()){out["status"]="invalid";out["reason"]="ball_candidate_missing";return out;}
    std::vector<cv::Point2d>a{{lp[0].get<double>(),lp[1].get<double>()}},b{{rp[0].get<double>(),rp[1].get<double>()}},ar,br; cv::undistortPoints(a,ar,cal_.k1,cal_.d1,cal_.r1,cal_.p1); cv::undistortPoints(b,br,cal_.k2,cal_.d2,cal_.r2,cal_.p2);
    double epi=std::abs(ar[0].y-br[0].y),disp=ar[0].x-br[0].x; out["left_pixel"]={a[0].x,a[0].y}; out["right_pixel"]={b[0].x,b[0].y}; out["epipolar_error_px"]=epi; out["disparity_px"]=disp;
    if(epi>3||disp<=.5){out["status"]="invalid";out["reason"]=epi>3?"epipolar_mismatch":"nonpositive_or_tiny_disparity";return out;}
    cv::Mat h; cv::triangulatePoints(cal_.p1,cal_.p2,ar,br,h); double w=h.at<double>(3); if(std::abs(w)<1e-12){out["status"]="invalid";out["reason"]="point_at_infinity";return out;} cv::Mat rect=h.rowRange(0,3)/w,cam=cal_.r1.t()*rect,right=cal_.r*cam+cal_.t;
    if(cam.at<double>(2)<=.1||cam.at<double>(2)>15||right.at<double>(2)<=.1){out["status"]="invalid";out["reason"]="invalid_depth";return out;}
    out["status"]="observed"; out["camera_xyz_m"]={cam.at<double>(0),cam.at<double>(1),cam.at<double>(2)}; out["source"]="c_detection_same_frame"; return out;
  }
  bool requestRightDetection(const FramePair&,const MotionResult&) const override{return true;}
  std::string version() const override{return "b-auto-measure-track-module-v0.1";}
 private: Cal cal_;
};
void register_b_module(Registry& registry){registry.measurement=[](){return std::make_unique<BMeasurement>();};}
}
