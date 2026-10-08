#include "ball_measurement.hpp"
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace pingpong::ball;
namespace {
void require(bool value, const std::string& message) { if (!value) throw std::runtime_error(message); }
FrameStamp stamp(Eye eye = Eye::Left) { return {10, eye, 1000000000, "gray1280-search640", "b-measure-v2-draft", "synthetic-v1"}; }
GrayFrame frame(Eye eye = Eye::Left, int background = 25) { return {cv::Mat(720,1280,CV_8U,cv::Scalar(background)), stamp(eye)}; }
MotionFrame motion(Eye eye = Eye::Left) { MotionFrame m; m.mask=cv::Mat::zeros(360,640,CV_8U); m.stamp=stamp(eye); m.reference_valid=true; m.reference_id=9; return m; }
void ball(GrayFrame& f, MotionFrame& m, cv::Point p={640,360}, int radius=12, int value=235) {
    cv::circle(f.gray,p,radius,cv::Scalar(value),-1);
    cv::circle(m.mask,cv::Point(p.x/2,p.y/2),std::max(3,radius/2),cv::Scalar(255),-1);
}
PredictionHint hint(const GrayFrame& f, cv::Point2f p={640,360}) { return {f.stamp,9,983333333,p,24,"external-test-predictor"}; }
void observed_at(const EyeResult& r, cv::Point2f p, double tolerance=1) {
    require(r.source==MeasurementSource::Observed && r.observation.has_value(),"expected observed: "+r.reason);
    require(cv::norm(r.observation->image_center-p)<=tolerance,"incorrect center");
    require(r.observation->identity_validated,"identity not validated");
}
void rejected(const EyeResult& r, const std::string& reason) {
    require(r.source==MeasurementSource::Invalid && !r.observation,"false observation");
    require(r.reason==reason,"expected "+reason+" got "+r.reason);
}
}
int main(int argc,char** argv) {
    const std::string group=argc>1?argv[1]:"all";
    int passed=0,failed=0;
    const auto test=[&](const char* name,const std::function<void()>& body) {
        try {body();++passed;std::cout<<"PASS "<<name<<'\n';}
        catch(const std::exception& e){++failed;std::cerr<<"FAIL "<<name<<": "<<e.what()<<'\n';}
    };
    Config cfg;
    if(group=="all" || group=="selection") {
        test("bright_ball",[&]{auto f=frame();auto m=motion();ball(f,m);auto r=measure_eye(f,m,cfg);observed_at(r,{640,360});require(r.observation->polarity==Polarity::Bright,"wrong polarity");});
        test("dark_ball",[&]{auto f=frame(Eye::Left,230);auto m=motion();ball(f,m,{640,360},12,25);auto r=measure_eye(f,m,cfg);observed_at(r,{640,360});require(r.observation->polarity==Polarity::Dark,"wrong polarity");});
        test("uniform_false_mask",[&]{auto f=frame();auto m=motion();cv::circle(m.mask,{320,180},9,255,-1);rejected(measure_eye(f,m,cfg),"low_local_contrast");});
        test("uniform_dark_background",[&]{auto f=frame(Eye::Left,230);auto m=motion();cv::circle(m.mask,{320,180},9,255,-1);rejected(measure_eye(f,m,cfg),"low_local_contrast");});
        test("low_contrast_ball",[&]{auto f=frame(Eye::Left,100);auto m=motion();ball(f,m,{640,360},12,105);rejected(measure_eye(f,m,cfg),"low_local_contrast");});
        test("selected_component_not_all_foreground",[&]{auto f=frame();auto m=motion();ball(f,m,{640,360},8);cv::circle(f.gray,{661,374},5,235,-1);auto r=measure_eye(f,m,cfg);observed_at(r,{640,360});require(r.observation->area<260,"summed unrelated object");});
        test("background_step_rejected",[&]{auto f=frame();auto m=motion();f.gray(cv::Rect(640,0,640,720)).setTo(235);cv::circle(m.mask,{320,180},8,255,-1);require(measure_eye(f,m,cfg).source==MeasurementSource::Invalid,"step false positive");});
        test("elongated_region_rejected",[&]{auto f=frame();auto m=motion();cv::rectangle(f.gray,{621,354,38,12},235,-1);cv::circle(m.mask,{320,180},8,255,-1);require(measure_eye(f,m,cfg).source==MeasurementSource::Invalid,"elongated object accepted");});
        test("local_equal_candidates_ambiguous",[&]{auto f=frame();auto m=motion();cv::circle(f.gray,{626,360},8,235,-1);cv::circle(f.gray,{654,360},8,235,-1);cv::circle(m.mask,{320,180},6,255,-1);rejected(measure_eye(f,m,cfg),"ambiguous_local_components");});
        test("old_position_mask_uses_current_gray",[&]{auto f=frame();auto m=motion();ball(f,m,{700,360});cv::circle(m.mask,{300,180},8,255,-1);observed_at(measure_eye(f,m,cfg),{700,360});});
        test("candidate_limit_and_prediction_order",[&]{auto m=motion();for(int i=0;i<12;++i)cv::circle(m.mask,{40+i*40,100},6,255,-1);auto f=frame();auto h=hint(f,{880.5f,200.5f});auto c=connected_components_8u(m.mask,cfg,h);require(c.size()==8,"not capped at eight");require(cv::norm(search_to_image(c.front().search_center,cfg)-h.image_center)<1,"prediction distance ignored");});
        test("fractional_centroid",[&]{auto f=frame();auto m=motion();ball(f,m,{640,360},8);cv::circle(f.gray,{641,360},8,235,-1);auto r=measure_eye(f,m,cfg);observed_at(r,{640.5f,360},0.6);require(std::abs(r.observation->image_center.x-std::round(r.observation->image_center.x))>0.2,"fractional center lost");});
    }
    if(group=="all" || group=="identity") {
        test("coordinate_mapping",[&]{require(cv::norm(search_to_image({3.25f,4.75f},cfg)-cv::Point2f(7,10))<1e-6,"mapping not 2u+0.5");});
        test("roi_four_edges_and_stride",[&]{cv::Mat storage(720,1297,CV_8U);cv::Mat image=storage(cv::Rect(0,0,1280,720));for(int y=0;y<720;++y)for(int x=0;x<1280;++x)image.at<unsigned char>(y,x)=static_cast<unsigned char>((3*x+7*y)%251);for(auto p:{cv::Point2f(0,0),cv::Point2f(1279,0),cv::Point2f(0,719),cv::Point2f(1279,719),cv::Point2f(640,360)}) {auto r=extract_roi(image,p,cfg);require(r.gray.size()==cv::Size(256,256),"ROI size wrong");require(cv::countNonZero(r.valid_mask)==r.valid.area(),"valid mask wrong");for(int y=0;y<256;++y)for(int x=0;x<256;++x){int ix=std::clamp(r.requested.x+x,0,1279),iy=std::clamp(r.requested.y+y,0,719);require(r.gray.at<unsigned char>(y,x)==image.at<unsigned char>(iy,ix),"replicate/source mapping wrong");}}});
        test("padded_roi_unclipped_ball",[&]{auto f=frame();auto m=motion();ball(f,m,{18,18},8);auto r=measure_eye(f,m,cfg);observed_at(r,{18,18});require(r.observation->requested_roi.x<0 && r.observation->roi_valid.x>0,"padding not recorded");require(!r.observation->quality.touches_image_boundary,"unclipped ball rejected");});
        const auto mismatch=[&](const char* name,const char* reason,std::function<void(MotionFrame&)> change){test(name,[&]{auto f=frame();auto m=motion();ball(f,m);change(m);auto r=measure_eye(f,m,cfg);rejected(r,reason);require(r.attempts.empty(),"pixels processed before identity check");});};
        mismatch("wrong_pair","pair_id_mismatch",[](auto& m){++m.stamp.pair_id;});
        mismatch("wrong_eye","eye_mismatch",[](auto& m){m.stamp.eye=Eye::Right;});
        mismatch("wrong_time","sample_time_mismatch",[](auto& m){++m.stamp.sample_time_ns;});
        mismatch("wrong_mode","mode_mismatch",[](auto& m){m.stamp.mode_id="other";});
        mismatch("wrong_version","config_version_mismatch",[](auto& m){m.stamp.config_version="other";});
        mismatch("wrong_calibration","calibration_version_mismatch",[](auto& m){m.stamp.calibration_version="other";});
        mismatch("failed_motion","motion_failed",[](auto& m){m.valid=false;});
        mismatch("missing_reference","missing_reference_id",[](auto& m){m.reference_id.reset();});
        mismatch("future_reference","invalid_reference_state",[](auto& m){m.reference_id=11;});
        test("missing_metadata",[&]{auto f=frame();auto m=motion();f.stamp.mode_id.clear();rejected(measure_eye(f,m,cfg),"missing_frame_metadata");});
        test("active_configuration_checked",[&]{auto f=frame();auto m=motion();f.stamp.config_version=m.stamp.config_version="other";rejected(measure_eye(f,m,cfg),"active_config_version_mismatch");});
        test("bad_size",[&]{auto f=frame();auto m=motion();f.gray=cv::Mat::zeros(100,100,CV_8U);rejected(measure_eye(f,m,cfg),"invalid_gray_image");});
        test("stereo_pair_identity",[&]{auto l=frame(),r=frame(Eye::Right);auto lm=motion(),rm=motion(Eye::Right);ball(l,lm,{640,360});ball(r,rm,{615,358});auto pair=measure_pair(l,r,lm,rm,cfg);require(pair.both_observed && pair.identity_validated,"valid stereo pair failed");++r.stamp.pair_id;auto bad=measure_pair(l,r,lm,rm,cfg);require(!bad.identity_validated && bad.reason=="stereo_pair_id_mismatch","cross-frame stereo accepted");});
    }
    if(group=="all" || group=="quality") {
        test("image_truncation_rejected_with_evidence",[&]{auto f=frame();auto m=motion();ball(f,m,{5,360},12);auto r=measure_eye(f,m,cfg);require(r.source==MeasurementSource::Invalid,"biased clipped center accepted");require(!r.attempts.empty() && r.attempts[0].quality.touches_image_boundary,"missing edge flag");require(!std::isfinite(r.attempts[0].image_center.x),"invalid center looks measured");});
        test("local_window_truncation",[&]{auto f=frame();auto m=motion();cv::circle(f.gray,{661,360},16,235,-1);cv::circle(m.mask,{320,180},8,255,-1);auto r=measure_eye(f,m,cfg);rejected(r,"local_boundary_truncation");require(r.attempts.front().quality.touches_local_boundary,"local boundary flag missing");});
        test("severe_occlusion_rejected",[&]{auto f=frame();auto m=motion();ball(f,m,{640,360},16);cv::rectangle(f.gray,{635,340,30,40},25,-1);require(measure_eye(f,m,cfg).source==MeasurementSource::Invalid,"severely biased centroid accepted");});
        test("clear_quality_sobel",[&]{auto f=frame();auto m=motion();ball(f,m);auto r=measure_eye(f,m,cfg);observed_at(r,{640,360});require(r.observation->quality.level==QualityLevel::Clear,"clear ball reduced");require(r.observation->quality.contrast>100 && r.observation->quality.edge_coverage>0.8,"Sobel/background metrics missing");});
        test("partial_occlusion_quality_warning",[&]{auto f=frame();auto m=motion();ball(f,m,{640,360},16);cv::rectangle(f.gray,{650,342,15,36},25,-1);auto r=measure_eye(f,m,cfg);require(!r.attempts.empty(),"no quality evidence");const auto& q=r.attempts[0].quality;require(q.possible_occlusion || r.source==MeasurementSource::Invalid,"occlusion silent");if(r.observation)require(q.level==QualityLevel::Reduced,"uncertain contour marked clear");});
        test("zero_mask_remeasurement",[&]{auto f=frame();auto m=motion();cv::circle(f.gray,{643,359},12,235,-1);auto r=measure_eye(f,m,cfg,hint(f));observed_at(r,{643,359});require(r.observation->search_source==SearchSource::Prediction && r.prediction,"prediction seed confused with observation");require(cv::norm(r.prediction->image_center-r.observation->image_center)>1,"copied prediction instead of measuring");});
        test("prediction_only_no_ball",[&]{auto f=frame();auto m=motion();auto r=measure_eye(f,m,cfg,hint(f));require(r.source==MeasurementSource::Predicted && !r.observation && r.prediction,"fabricated observation");require(r.attempts.back().reason=="low_local_contrast","no-ball reason missing");});
        test("zero_mask_no_prediction",[&]{auto f=frame();auto m=motion();rejected(measure_eye(f,m,cfg),"no_motion_candidates");});
        test("stale_prediction_rejected",[&]{auto f=frame();auto m=motion();auto h=hint(f);h.source_sample_time_ns=100;rejected(measure_eye(f,m,cfg,h),"invalid_or_stale_prediction");});
        test("prediction_does_not_switch_to_distant_object",[&]{auto f=frame();auto m=motion();ball(f,m,{900,360});auto r=measure_eye(f,m,cfg,hint(f));require(r.source==MeasurementSource::Predicted && !r.observation,"switched to distant round object");require(r.attempts.front().reason=="outside_prediction_gate","gate not recorded");});
        test("wrong_prediction_target",[&]{auto f=frame();auto m=motion();auto h=hint(f);h.target.eye=Eye::Right;rejected(measure_eye(f,m,cfg,h),"prediction_target_mismatch");});
        test("large_timestamp_retains_nanoseconds",[&]{auto f=frame();auto m=motion();f.stamp.sample_time_ns=m.stamp.sample_time_ns=1700000000000000000LL;auto h=hint(f);h.source_sample_time_ns=f.stamp.sample_time_ns-1;auto r=measure_eye(f,m,cfg,h);require(r.source==MeasurementSource::Predicted,"lost real timestamp dt");});
        test("first_frame_zero_mask",[&]{auto f=frame();auto m=motion();m.reference_valid=false;m.reference_id.reset();rejected(measure_eye(f,m,cfg),"no_motion_candidates");cv::circle(m.mask,{320,180},8,255,-1);rejected(measure_eye(f,m,cfg),"uninitialized_motion_nonzero");});
        test("distinct_objects_require_identity",[&]{auto f=frame();auto m=motion();ball(f,m,{300,300});ball(f,m,{900,300});rejected(measure_eye(f,m,cfg),"ambiguous_frame_candidates");auto r=measure_eye(f,m,cfg,hint(f,{900,300}));observed_at(r,{900,300});});
    }
    std::cout<<"BALL_MEASUREMENT_TESTS passed="<<passed<<" failed="<<failed<<" group="<<group<<'\n';
    return failed || passed==0 ? 1:0;
}
