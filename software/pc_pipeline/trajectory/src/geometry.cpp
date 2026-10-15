#include "trajectory.hpp"
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace pingpong::trajectory {
namespace {
bool good(const cv::Mat& m,int rows,int cols) { return m.type()==CV_64F && m.rows==rows && m.cols==cols && cv::checkRange(m); }
bool rotation(const cv::Mat& r) { return good(r,3,3) && cv::norm(r*r.t()-cv::Mat::eye(3,3,CV_64F))<1e-6 && std::abs(cv::determinant(r)-1)<1e-6; }
bool finite(cv::Point2d p) { return std::isfinite(p.x)&&std::isfinite(p.y); }
bool stamp_equal(const FrameStamp& a,const FrameStamp& b) { return a.pair_id==b.pair_id && a.sample_time_ns==b.sample_time_ns && a.mode_id==b.mode_id && a.config_version==b.config_version && a.calibration_version==b.calibration_version; }
cv::Vec3d vec(const cv::Mat& m) { return {m.at<double>(0),m.at<double>(1),m.at<double>(2)}; }
cv::Vec3d reconstruct(cv::Point2d l,cv::Point2d r,const Calibration& c,cv::Vec3d* camera=nullptr) {
    std::vector<cv::Point2d> a{l},b{r},ar,br;
    cv::undistortPoints(a,ar,c.K1,c.D1,c.R1,c.P1);
    cv::undistortPoints(b,br,c.K2,c.D2,c.R2,c.P2);
    cv::Mat h;cv::triangulatePoints(c.P1,c.P2,ar,br,h);
    if(std::abs(h.at<double>(3))<1e-12)throw std::runtime_error("degenerate_homogeneous_point");
    cv::Mat rect=h.rowRange(0,3)/h.at<double>(3);
    cv::Mat cam=c.R1.t()*rect;
    if(camera)*camera=vec(cam);
    return vec(c.Rcw.t()*(cam-c.tcw));
}
}
bool validate_calibration(const Calibration& c,std::string& why) {
    if(c.version.empty()||c.provenance.empty()||c.size!=cv::Size(1280,720))why="calibration_metadata_or_size";
    else if(c.unit!="m")why="calibration_not_metric";
    else if(!good(c.K1,3,3)||!good(c.K2,3,3)||c.K1.at<double>(0,0)<=0||c.K2.at<double>(0,0)<=0||c.K1.at<double>(1,1)<=0||c.K2.at<double>(1,1)<=0||std::abs(c.K1.at<double>(2,2)-1)>1e-9||std::abs(c.K2.at<double>(2,2)-1)>1e-9)why="invalid_intrinsics";
    else if(c.D1.type()!=CV_64F||c.D2.type()!=CV_64F||(c.D1.rows!=1&&c.D1.cols!=1)||(c.D2.rows!=1&&c.D2.cols!=1)||
        (c.D1.total()!=4&&c.D1.total()!=5&&c.D1.total()!=8&&c.D1.total()!=12&&c.D1.total()!=14)||
        (c.D2.total()!=4&&c.D2.total()!=5&&c.D2.total()!=8&&c.D2.total()!=12&&c.D2.total()!=14)||!cv::checkRange(c.D1)||!cv::checkRange(c.D2))why="invalid_distortion";
    else if(!rotation(c.R)||!good(c.T,3,1)||cv::norm(c.T)<0.01)why="invalid_stereo_pose";
    else if(!rotation(c.R1)||!rotation(c.R2)||!good(c.P1,3,4)||!good(c.P2,3,4))why="invalid_rectification";
    else if(!c.world_valid||!rotation(c.Rcw)||!good(c.tcw,3,1))why="world_pose_unavailable";
    else {Calibration expected=c;expected.R1.release();expected.R2.release();expected.P1.release();expected.P2.release();rectify(expected);if(cv::norm(expected.R1-c.R1)>1e-6||cv::norm(expected.R2-c.R2)>1e-6||cv::norm(expected.P1-c.P1)>1e-5||cv::norm(expected.P2-c.P2)>1e-5){why="stale_rectification";return false;}why.clear();return true; }
    return false;
}
void rectify(Calibration& c) {
    cv::Mat q;cv::stereoRectify(c.K1,c.D1,c.K2,c.D2,c.size,c.R,c.T,c.R1,c.R2,c.P1,c.P2,q,cv::CALIB_ZERO_DISPARITY,0,c.size);
}
void save_calibration(const Calibration& c,const std::string& path) {
    cv::FileStorage f(path,cv::FileStorage::WRITE|cv::FileStorage::FORMAT_JSON);
    if(!f.isOpened())throw std::runtime_error("cannot_write_calibration");
    f<<"schema"<<"b-calibration-v1-draft"<<"version"<<c.version<<"unit"<<c.unit<<"provenance"<<c.provenance<<"width"<<c.size.width<<"height"<<c.size.height<<"world_valid"<<int(c.world_valid)
      <<"K1"<<c.K1<<"D1"<<c.D1<<"K2"<<c.K2<<"D2"<<c.D2<<"R"<<c.R<<"T"<<c.T<<"R1"<<c.R1<<"R2"<<c.R2<<"P1"<<c.P1<<"P2"<<c.P2<<"Rcw"<<c.Rcw<<"tcw"<<c.tcw
      <<"mono_rms_left"<<c.mono_rms_left<<"mono_rms_right"<<c.mono_rms_right<<"stereo_rms"<<c.stereo_rms;
}
Calibration load_calibration(const std::string& path) {
    cv::FileStorage f(path,cv::FileStorage::READ);if(!f.isOpened())throw std::runtime_error("cannot_read_calibration");
    Calibration c; const std::string schema=static_cast<std::string>(f["schema"]);
    if(schema=="b-calibration-v1-draft" && !f["width"].empty()) {
        f["version"]>>c.version;f["unit"]>>c.unit;f["provenance"]>>c.provenance;c.size={int(f["width"]),int(f["height"])};c.world_valid=int(f["world_valid"])!=0;
        f["K1"]>>c.K1;f["D1"]>>c.D1;f["K2"]>>c.K2;f["D2"]>>c.D2;f["R"]>>c.R;f["T"]>>c.T;f["R1"]>>c.R1;f["R2"]>>c.R2;f["P1"]>>c.P1;f["P2"]>>c.P2;f["Rcw"]>>c.Rcw;f["tcw"]>>c.tcw;
        c.mono_rms_left=double(f["mono_rms_left"]);c.mono_rms_right=double(f["mono_rms_right"]);c.stereo_rms=double(f["stereo_rms"]);return c;
    }
    // The delivered calibration snapshot uses the project-facing JSON schema.
    // Convert it here so the B CLI can consume the same file as A and C.
    if(!f["K_left"].empty()) {
        f["K_left"]>>c.K1; f["D_left"]>>c.D1; f["K_right"]>>c.K2; f["D_right"]>>c.D2;
        f["R_left_to_right"]>>c.R; f["T_m"]>>c.T; f["R1"]>>c.R1; f["R2"]>>c.R2; f["P1"]>>c.P1; f["P2"]>>c.P2;
        c.size={int(f["image_size_px"][0]),int(f["image_size_px"][1])}; c.unit="m"; c.world_valid=true;
        // No table-world transform is used in this task.  Keep the output
        // frame explicitly equal to the left camera frame.
        c.Rcw=cv::Mat::eye(3,3,CV_64F); c.tcw=cv::Mat::zeros(3,1,CV_64F);
        c.version="ov9281-20261014"; c.provenance="project calibration_results.json; left_camera_frame fallback";
        c.mono_rms_left=double(f["left_rms_px"]); c.mono_rms_right=double(f["right_rms_px"]); c.stereo_rms=double(f["stereo_rms_px"]);
        return c;
    }
    throw std::runtime_error("calibration_schema");
}
Calibration calibrate_chessboards(const std::vector<cv::Mat>& l,const std::vector<cv::Mat>& r,cv::Size corners,double side,const std::string& unit,const std::string& version) {
    if(l.size()!=r.size()||l.size()<8||side<=0||corners.width<3||corners.height<3||(unit!="m"&&unit!="square"))throw std::runtime_error("invalid_board_input");
    std::vector<std::vector<cv::Point3f>> objects;std::vector<std::vector<cv::Point2f>> lp,rp;
    std::vector<cv::Point3f> grid;for(int y=0;y<corners.height;++y)for(int x=0;x<corners.width;++x)grid.emplace_back(float(x*side),float(y*side),0.0f);
    for(std::size_t i=0;i<l.size();++i){if(l[i].size()!=cv::Size(1280,720)||r[i].size()!=l[i].size()||l[i].type()!=CV_8UC1||r[i].type()!=CV_8UC1)throw std::runtime_error("board_size_or_type");
        std::vector<cv::Point2f>a,b;if(cv::findChessboardCornersSB(l[i],corners,a,cv::CALIB_CB_NORMALIZE_IMAGE)&&cv::findChessboardCornersSB(r[i],corners,b,cv::CALIB_CB_NORMALIZE_IMAGE)){objects.push_back(grid);lp.push_back(a);rp.push_back(b);}}
    if(objects.size()<8)throw std::runtime_error("insufficient_detected_board_pairs");
    Calibration c;c.version=version;c.unit=unit;c.provenance="chessboard_images; scale declared by caller; not a real-camera certificate";
    std::vector<cv::Mat>rv,tv;c.mono_rms_left=cv::calibrateCamera(objects,lp,c.size,c.K1,c.D1,rv,tv);c.mono_rms_right=cv::calibrateCamera(objects,rp,c.size,c.K2,c.D2,rv,tv);
    cv::Mat E,F;c.stereo_rms=cv::stereoCalibrate(objects,lp,rp,c.K1,c.D1,c.K2,c.D2,c.size,c.R,c.T,E,F,cv::CALIB_FIX_INTRINSIC,cv::TermCriteria(cv::TermCriteria::COUNT|cv::TermCriteria::EPS,100,1e-8));rectify(c);return c;
}
bool set_world_pose(Calibration& c,const std::vector<cv::Point3d>& world,const std::vector<cv::Point2d>& pixels,std::string& why) {
    if(c.unit!="m"||world.size()!=pixels.size()||world.size()<6){why="world_points_or_units";return false;}
    cv::Mat rv,tv;bool ok=cv::solvePnP(world,pixels,c.K1,c.D1,rv,tv,false,cv::SOLVEPNP_ITERATIVE);if(!ok){why="world_pose_failed";return false;}
    std::vector<cv::Point2d> projected;cv::projectPoints(world,rv,tv,c.K1,c.D1,projected);double error=0;for(std::size_t i=0;i<pixels.size();++i)error+=cv::norm(projected[i]-pixels[i]);
    if(error/pixels.size()>2){why="world_pose_reprojection";return false;}
    cv::Rodrigues(rv,c.Rcw);c.tcw=tv;c.world_valid=true;why.clear();return true;
}
bool rectify_images(const Calibration& c,const cv::Mat& l,const cv::Mat& r,cv::Mat& lo,cv::Mat& ro,std::string& why){
    lo.release();ro.release();
    if(l.type()!=CV_8UC1||r.type()!=CV_8UC1||l.size()!=c.size||r.size()!=c.size||!good(c.K1,3,3)||!good(c.K2,3,3)||!rotation(c.R1)||!rotation(c.R2)||!good(c.P1,3,4)||!good(c.P2,3,4)){why="rectification_preview_input";return false;}
    try{cv::Mat mx,my;cv::initUndistortRectifyMap(c.K1,c.D1,c.R1,c.P1,c.size,CV_32FC1,mx,my);cv::remap(l,lo,mx,my,cv::INTER_LINEAR,cv::BORDER_CONSTANT);
        cv::initUndistortRectifyMap(c.K2,c.D2,c.R2,c.P2,c.size,CV_32FC1,mx,my);cv::remap(r,ro,mx,my,cv::INTER_LINEAR,cv::BORDER_CONSTANT);
    }catch(const cv::Exception&){why="rectification_preview_failed";lo.release();ro.release();return false;}
    why.clear();return true;
}
std::optional<PixelObservation> from_measurement(const ball::EyeResult& r) {
    if(r.source!=ball::MeasurementSource::Observed||!r.observation||!r.observation->identity_validated)return std::nullopt;
    const auto& m=*r.observation;PixelObservation p;p.stamp=m.stamp;p.center=m.image_center;p.diameter_px=2*std::sqrt(m.area/CV_PI);p.reduced=m.quality.level!=ball::QualityLevel::Clear;p.sigma_px=p.reduced?2:0.3;return p;
}
std::vector<PixelObservation> observation_candidates(const ball::EyeResult& r){
    std::vector<PixelObservation> points;
    for(const auto& m:r.attempts){
        if(m.source!=ball::MeasurementSource::Observed||!m.identity_validated)continue;
        PixelObservation p;p.stamp=m.stamp;p.center=m.image_center;p.diameter_px=2*std::sqrt(m.area/CV_PI);p.reduced=m.quality.level!=ball::QualityLevel::Clear;p.sigma_px=p.reduced?2:.3;
        bool duplicate=false;for(const auto& old:points)if(cv::norm(old.center-p.center)<2)duplicate=true;
        if(!duplicate&&points.size()<8)points.push_back(p);
    }
    if(points.empty()){auto p=from_measurement(r);if(p)points.push_back(*p);}return points;
}
std::optional<cv::Point2d> project(const cv::Vec3d& world,Eye eye,const Calibration& c) {
    std::string why;if(!validate_calibration(c,why))return std::nullopt;
    cv::Mat cam=c.Rcw*cv::Mat(world)+c.tcw;if(eye==Eye::Right)cam=c.R*cam+c.T;
    if(!cv::checkRange(cam)||cam.at<double>(2)<=0)return std::nullopt;
    std::vector<cv::Point3d>p{{cam.at<double>(0),cam.at<double>(1),cam.at<double>(2)}};std::vector<cv::Point2d>out;
    cv::projectPoints(p,cv::Vec3d(),cv::Vec3d(),eye==Eye::Left?c.K1:c.K2,eye==Eye::Left?c.D1:c.D2,out);
    if(!finite(out[0])||out[0].x<0||out[0].y<0||out[0].x>=c.size.width||out[0].y>=c.size.height)return std::nullopt;return out[0];
}
WorldObservation triangulate(const PixelObservation& l,const PixelObservation& r,const Calibration& c,const GeometryConfig& cfg) {
    WorldObservation out;out.stamp=l.stamp;out.left=l.center;out.right=r.center;
    const auto fail=[&](const std::string& reason){out.reason=reason;return out;};std::string why;
    if(!std::isfinite(cfg.epipolar_px)||cfg.epipolar_px<=0||!std::isfinite(cfg.reprojection_px)||cfg.reprojection_px<=0||!std::isfinite(cfg.min_disparity_px)||cfg.min_disparity_px<=0||!std::isfinite(cfg.min_depth_m)||cfg.min_depth_m<=0||!std::isfinite(cfg.max_depth_m)||cfg.max_depth_m<=cfg.min_depth_m||!std::isfinite(cfg.max_diameter_ratio)||cfg.max_diameter_ratio<1)return fail("invalid_geometry_config");
    for(double x:{cfg.calibration_position_sigma_m,cfg.world_translation_sigma_m,cfg.world_rotation_sigma_rad,cfg.sync_sigma_s,cfg.sync_speed_bound_m_s})if(!std::isfinite(x)||x<0)return fail("invalid_uncertainty_budget");
    if(!validate_calibration(c,why))return fail(why);
    if(!l.observed||!r.observed||!l.identity_validated||!r.identity_validated)return fail("not_stereo_observations");
    if(l.stamp.eye!=Eye::Left||r.stamp.eye!=Eye::Right||!stamp_equal(l.stamp,r.stamp)||l.stamp.sample_time_ns<0||l.stamp.mode_id.empty()||l.stamp.config_version.empty())return fail("stereo_frame_identity");
    if(l.stamp.calibration_version!=c.version)return fail("calibration_version_mismatch");
    if(!finite(l.center)||!finite(r.center)||l.center.x<0||r.center.x<0||l.center.y<0||r.center.y<0||l.center.x>=1280||r.center.x>=1280||l.center.y>=720||r.center.y>=720||!std::isfinite(l.sigma_px)||!std::isfinite(r.sigma_px)||l.sigma_px<=0||r.sigma_px<=0||!std::isfinite(l.diameter_px)||!std::isfinite(r.diameter_px)||l.diameter_px<0||r.diameter_px<0)return fail("invalid_pixels_or_quality");
    if(l.diameter_px>0&&r.diameter_px>0&&std::max(l.diameter_px,r.diameter_px)/std::min(l.diameter_px,r.diameter_px)>cfg.max_diameter_ratio)return fail("diameter_mismatch");
    std::vector<cv::Point2d>a{l.center},b{r.center},ar,br;cv::undistortPoints(a,ar,c.K1,c.D1,c.R1,c.P1);cv::undistortPoints(b,br,c.K2,c.D2,c.R2,c.P2);
    // Current route is a horizontal-baseline rig; vertical stereo is rejected.
    if(std::abs(c.P2.at<double>(1,3))>std::abs(c.P2.at<double>(0,3)))return fail("vertical_stereo_not_supported");
    out.epipolar_error_px=std::abs(ar[0].y-br[0].y);out.disparity_px=ar[0].x-br[0].x;
    if(out.epipolar_error_px>cfg.epipolar_px)return fail("epipolar_mismatch");
    if(std::abs(out.disparity_px)<cfg.min_disparity_px)return fail("low_disparity");
    try{out.world=reconstruct(l.center,r.center,c,&out.camera);}catch(const std::exception& e){return fail(e.what());}
    cv::Mat rc=c.R*cv::Mat(out.camera)+c.T;
    if(!cv::checkRange(cv::Mat(out.world))||out.camera[2]<cfg.min_depth_m||out.camera[2]>cfg.max_depth_m||rc.at<double>(2)<cfg.min_depth_m)return fail("nonpositive_or_out_of_range_depth");
    auto lp=project(out.world,Eye::Left,c),rp=project(out.world,Eye::Right,c);
    if(!lp||!rp)return fail("projection_outside_image");
    out.reprojection_error_px=std::max(cv::norm(*lp-l.center),cv::norm(*rp-r.center));if(out.reprojection_error_px>cfg.reprojection_px)return fail("reprojection_mismatch");
    cv::Matx<double,3,4>J;const double eps=1e-3;for(int i=0;i<4;++i){auto al=l.center,bl=r.center,ah=l.center,bh=r.center;if(i<2){(i==0?al.x:al.y)-=eps;(i==0?ah.x:ah.y)+=eps;}else{(i==2?bl.x:bl.y)-=eps;(i==2?bh.x:bh.y)+=eps;}auto d=(reconstruct(ah,bh,c)-reconstruct(al,bl,c))/(2*eps);for(int k=0;k<3;++k)J(k,i)=d[k];}
    cv::Matx44d noise=cv::Matx44d::zeros();noise(0,0)=noise(1,1)=l.sigma_px*l.sigma_px;noise(2,2)=noise(3,3)=r.sigma_px*r.sigma_px;out.covariance=J*noise*J.t()+cv::Matx33d::eye()*1e-8;
    const double extra=std::pow(cfg.calibration_position_sigma_m,2)+std::pow(cfg.world_translation_sigma_m,2)+std::pow(cfg.world_rotation_sigma_rad*cv::norm(out.camera),2)+std::pow(cfg.sync_sigma_s*cfg.sync_speed_bound_m_s,2);
    if(extra>0){out.covariance+=cv::Matx33d::eye()*extra;out.uncertainty_scope="pixel_noise_plus_caller_declared_budget_not_calibrated";}
    out.valid=true;out.reduced=l.reduced||r.reduced;out.reason=out.reduced?"observed_reduced_quality":"ok";return out;
}
StereoMatch match_stereo(const std::vector<PixelObservation>& left,const std::vector<PixelObservation>& right,const Calibration& c,const std::optional<cv::Vec3d>& predicted,const GeometryConfig& cfg){
    StereoMatch result;if(left.size()>8||right.size()>8){result.reason="candidate_capacity_exceeded";return result;}
    struct Choice{double cost;std::size_t l,r;WorldObservation w;};std::vector<Choice>choices;
    auto pl=predicted?project(*predicted,Eye::Left,c):std::nullopt,pr=predicted?project(*predicted,Eye::Right,c):std::nullopt;
    if(predicted&&(!pl||!pr)){result.reason="invalid_pair_prediction";return result;}
    for(std::size_t i=0;i<left.size();++i)for(std::size_t j=0;j<right.size();++j){auto w=triangulate(left[i],right[j],c,cfg);if(!w.valid)continue;double cost=w.epipolar_error_px/cfg.epipolar_px+w.reprojection_error_px/cfg.reprojection_px;
        if(left[i].diameter_px>0&&right[j].diameter_px>0)cost+=std::abs(std::log(left[i].diameter_px/right[j].diameter_px));
        if(predicted){const double dl=cv::norm(left[i].center-*pl),dr=cv::norm(right[j].center-*pr);if(dl>24||dr>24)continue;cost+=(dl+dr)/24;}
        choices.push_back({cost,i,j,w});}
    if(choices.empty()){result.reason="no_valid_stereo_pair";return result;}
    std::sort(choices.begin(),choices.end(),[](const auto&a,const auto&b){return a.cost<b.cost;});
    for(std::size_t k=1;k<choices.size();++k)if(cv::norm(choices[k].w.world-choices[0].w.world)>.01&&choices[k].cost-choices[0].cost<.15){result.reason="ambiguous_stereo_pairs";return result;}
    result.valid=true;result.reason="geometry_hypothesis_semantic_identity_not_proven";result.left_index=choices[0].l;result.right_index=choices[0].r;result.observation=choices[0].w;return result;
}
} // namespace
