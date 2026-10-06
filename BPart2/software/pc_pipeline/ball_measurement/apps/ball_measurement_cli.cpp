#include "ball_measurement.hpp"
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>
namespace fs=std::filesystem;
using namespace pingpong::ball;
namespace {
std::uint64_t id(const cv::FileNode& n) {
    if(!n.isString())throw std::runtime_error("frame IDs must be decimal strings");
    const auto s=static_cast<std::string>(n); if(s.empty() || s.find_first_not_of("0123456789")!=std::string::npos)throw std::runtime_error("invalid ID");
    return std::stoull(s);
}
std::int64_t time_ns(const cv::FileNode& n) {const auto x=id(n);if(x>static_cast<std::uint64_t>(INT64_MAX))throw std::runtime_error("time out of range");return static_cast<std::int64_t>(x);}
FrameStamp read_stamp(const cv::FileNode& n) {
    FrameStamp s;s.pair_id=id(n["pair_id"]);s.sample_time_ns=time_ns(n["sample_time_ns"]);
    const auto eye=static_cast<std::string>(n["eye"]);if(eye!="left"&&eye!="right")throw std::runtime_error("invalid eye");s.eye=eye=="left"?Eye::Left:Eye::Right;
    s.mode_id=static_cast<std::string>(n["mode_id"]);s.config_version=static_cast<std::string>(n["config_version"]);s.calibration_version=static_cast<std::string>(n["calibration_version"]);return s;
}
void write_stamp(cv::FileStorage& f,const FrameStamp& s){f<<"pair_id"<<std::to_string(s.pair_id)<<"eye"<<to_string(s.eye)<<"sample_time_ns"<<std::to_string(s.sample_time_ns)<<"mode_id"<<s.mode_id<<"config_version"<<s.config_version<<"calibration_version"<<s.calibration_version;}
void rect(cv::FileStorage& f,const char* name,const cv::Rect& r){f<<name<<"["<<r.x<<r.y<<r.width<<r.height<<"]";}
void point(cv::FileStorage& f,const char* name,cv::Point2f p){f<<name<<"["<<p.x<<p.y<<"]";}
void write_measurement(cv::FileStorage& f,const Measurement& m){
    f<<"{";write_stamp(f,m.stamp);f<<"source"<<to_string(m.source)<<"search_source"<<to_string(m.search_source)<<"reason"<<m.reason<<"identity_validated"<<int(m.identity_validated);
    if(m.source==MeasurementSource::Observed)point(f,"image_center",m.image_center);
    point(f,"seed_image_center",m.seed_image_center);rect(f,"requested_roi",m.requested_roi);rect(f,"image_valid",m.roi);rect(f,"roi_valid",m.roi_valid);rect(f,"local_window",m.local_window);rect(f,"local_valid",m.local_valid);rect(f,"ball_bounds",m.ball_bounds);
    f<<"padding"<<m.padding<<"reference_valid"<<int(m.reference_valid);if(m.reference_id)f<<"reference_id"<<std::to_string(*m.reference_id);
    f<<"polarity"<<(m.polarity==Polarity::Bright?"bright":"dark")<<"otsu_threshold"<<m.otsu_threshold<<"area"<<m.area<<"circularity"<<m.circularity<<"edge_score"<<m.edge_score<<"selection_score"<<m.selection_score;
    const auto& q=m.quality;f<<"quality"<<"{"<<"level"<<to_string(q.level)<<"contrast"<<q.contrast<<"aspect_ratio"<<q.aspect_ratio<<"foreground_fraction"<<q.foreground_fraction<<"edge_coverage"<<q.edge_coverage<<"radial_asymmetry"<<q.radial_asymmetry<<"solidity"<<q.solidity<<"touches_image_boundary"<<int(q.touches_image_boundary)<<"touches_local_boundary"<<int(q.touches_local_boundary)<<"touches_roi_boundary"<<int(q.touches_roi_boundary)<<"possible_occlusion"<<int(q.possible_occlusion)<<"flags"<<"[";for(const auto& flag:q.flags)f<<flag;f<<"]"<<"}"<<"}";
}
void write_result(const fs::path& directory,const std::string& name,const EyeResult& r,const GrayFrame& frame){
    cv::FileStorage f((directory/(name+".json")).string(),cv::FileStorage::WRITE|cv::FileStorage::FORMAT_JSON);if(!f.isOpened())throw std::runtime_error("cannot write result");
    f<<"interface_version"<<"b-measure-v2-draft";write_stamp(f,r.stamp);f<<"source"<<to_string(r.source)<<"reason"<<r.reason<<"candidate_count"<<int(r.candidates.size());
    if(r.prediction){const auto& p=*r.prediction;f<<"prediction"<<"{"<<"source"<<"predicted"<<"source_pair_id"<<std::to_string(p.source_pair_id)<<"source_sample_time_ns"<<std::to_string(p.source_sample_time_ns)<<"predictor_version"<<p.predictor_version<<"previous_diameter_px"<<p.previous_diameter_px<<"target"<<"{";write_stamp(f,p.target);f<<"}";point(f,"image_center",p.image_center);f<<"}";}
    f<<"candidates"<<"[";for(const auto& c:r.candidates){f<<"{";point(f,"search_center",c.search_center);rect(f,"search_bounds",c.search_bounds);f<<"area"<<c.area<<"aspect_ratio"<<c.aspect_ratio<<"score"<<c.score<<"prediction_distance_px"<<c.prediction_distance_px<<"}";}f<<"]";
    if(r.observation){f<<"observation";write_measurement(f,*r.observation);}
    f<<"attempts"<<"[";for(const auto& m:r.attempts)write_measurement(f,m);f<<"]";f.release();
    cv::Mat overlay;cv::cvtColor(frame.gray,overlay,cv::COLOR_GRAY2BGR);
    if(r.prediction)cv::drawMarker(overlay,r.prediction->image_center,cv::Scalar(255,180,0),cv::MARKER_CROSS,12,1);
    if(r.observation)cv::drawMarker(overlay,r.observation->image_center,cv::Scalar(0,255,0),cv::MARKER_CROSS,14,1);
    cv::putText(overlay,name+": "+r.reason,{16,24},cv::FONT_HERSHEY_SIMPLEX,0.55,cv::Scalar(0,0,255),1);
    cv::imwrite((directory/(name+"_overlay.png")).string(),overlay);
    for(std::size_t i=0;i<r.attempts.size();++i){const auto& m=r.attempts[i];const auto prefix=name+"_attempt"+std::to_string(i);if(!m.local_gray.empty())cv::imwrite((directory/(prefix+"_local.png")).string(),m.local_gray);if(!m.selected_mask.empty())cv::imwrite((directory/(prefix+"_selected.png")).string(),m.selected_mask);}
}
} // namespace
int main(int argc,char** argv){try{
    if(argc!=3){std::cerr<<"usage: ball_measurement_cli <inputs/manifest.json> <output-directory>\n";return 2;}
    const fs::path manifest=argv[1],output=argv[2];fs::create_directories(output);
    cv::FileStorage input(manifest.string(),cv::FileStorage::READ);if(!input.isOpened())throw std::runtime_error("cannot read input manifest");
    const auto base=manifest.parent_path();int count=0;Config cfg;
    cv::FileStorage config((output/"config.json").string(),cv::FileStorage::WRITE|cv::FileStorage::FORMAT_JSON);
    config<<"config_version"<<cfg.config_version<<"search_width"<<cfg.search_width<<"search_height"<<cfg.search_height
        <<"image_width"<<cfg.image_width<<"image_height"<<cfg.image_height<<"roi_size"<<cfg.roi_size<<"local_size"<<cfg.local_size
        <<"search_to_image"<<cfg.search_to_image<<"search_center_offset"<<0.5<<"padding"<<"replicate"
        <<"min_search_area"<<cfg.min_area<<"max_search_area"<<cfg.max_area<<"min_search_extent"<<cfg.min_search_extent
        <<"max_search_extent"<<cfg.max_search_extent<<"max_search_aspect"<<cfg.max_search_aspect<<"max_candidates"<<cfg.max_candidates
        <<"min_ball_area"<<cfg.min_ball_area<<"max_ball_area"<<cfg.max_ball_area<<"min_ball_extent"<<cfg.min_ball_extent
        <<"max_ball_extent"<<cfg.max_ball_extent<<"max_ball_aspect"<<cfg.max_ball_aspect<<"min_circularity"<<cfg.min_circularity
        <<"min_dynamic_range"<<cfg.min_dynamic_range<<"min_contrast"<<cfg.min_contrast<<"max_foreground_fraction"<<cfg.max_foreground_fraction
        <<"max_seed_distance_px"<<cfg.max_seed_distance_px<<"ambiguity_margin"<<cfg.ambiguity_margin
        <<"sobel_min"<<cfg.sobel_min<<"max_prediction_age_s"<<cfg.max_prediction_age_s;
    config.release();
    for(const auto& n:input["cases"]){const auto name=static_cast<std::string>(n["name"]);if(name.empty()||name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)throw std::runtime_error("invalid case name");
        const auto image_node=n["image"],mask_node=n["motion"];
        GrayFrame frame{cv::imread((base/static_cast<std::string>(image_node["path"])).string(),cv::IMREAD_GRAYSCALE),read_stamp(image_node)};
        MotionFrame m;m.mask=cv::imread((base/static_cast<std::string>(mask_node["path"])).string(),cv::IMREAD_GRAYSCALE);m.stamp=read_stamp(mask_node);m.valid=int(mask_node["valid"])!=0;m.reference_valid=int(mask_node["reference_valid"])!=0;if(!mask_node["reference_id"].empty())m.reference_id=id(mask_node["reference_id"]);
        if(frame.gray.empty()||m.mask.empty())throw std::runtime_error("input image missing");
        std::optional<PredictionHint> prediction;
        if(!n["prediction"].empty()){const auto p=n["prediction"];PredictionHint h;h.target=read_stamp(p["target"]);h.source_pair_id=id(p["source_pair_id"]);h.source_sample_time_ns=time_ns(p["source_sample_time_ns"]);h.image_center={float(p["image_center"][0]),float(p["image_center"][1])};h.previous_diameter_px=float(p["previous_diameter_px"]);h.predictor_version=static_cast<std::string>(p["predictor_version"]);prediction=h;}
        const auto r=measure_eye(frame,m,cfg,prediction);write_result(output,name,r,frame);
        std::cout<<name<<": "<<to_string(r.source)<<" "<<r.reason<<'\n';++count;
    }
    std::cout<<"FILE_MEASUREMENT_COMPLETE cases="<<count<<'\n';return count?0:1;
}catch(const std::exception& e){std::cerr<<"ERROR "<<e.what()<<'\n';return 1;}}
