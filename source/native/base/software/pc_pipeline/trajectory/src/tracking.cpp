#include "trajectory.hpp"
#include <cmath>

namespace pingpong::trajectory {
Tracker Tracker::checkpoint() const {
    Tracker copy=*this;
    copy.state_=state_.clone();
    copy.covariance_=covariance_.clone();
    return copy;
}
namespace {
bool versions(const FrameStamp& a,const FrameStamp& b){return a.mode_id==b.mode_id&&a.config_version==b.config_version&&a.calibration_version==b.calibration_version;}
cv::Vec3d first3(const cv::Mat& s,int offset=0){return {s.at<double>(offset),s.at<double>(offset+1),s.at<double>(offset+2)};}
cv::Mat transition(double dt){cv::Mat f=cv::Mat::eye(6,6,CV_64F);for(int i=0;i<3;++i)f.at<double>(i,i+3)=dt;return f;}
cv::Mat gravity(double dt,double g,bool flight){cv::Mat b=cv::Mat::zeros(6,1,CV_64F);if(flight){b.at<double>(2)=-0.5*g*dt*dt;b.at<double>(5)=-g*dt;}return b;}
bool valid_observation(const WorldObservation& o,const FrameStamp& s){if(!o.valid||o.stamp.pair_id!=s.pair_id||o.stamp.sample_time_ns!=s.sample_time_ns||!versions(o.stamp,s)||!cv::checkRange(cv::Mat(o.world))||!cv::checkRange(cv::Mat(o.covariance))||cv::norm(cv::Mat(o.covariance-o.covariance.t()))>=1e-9)return false;cv::Mat eigen;cv::eigen(cv::Mat(o.covariance),eigen);return eigen.at<double>(2)>0;}
}
void Tracker::clear(){initialized_=false;state_.release();covariance_.release();last_flight_=false;rejected_streak_=0;last_rejected_position_.reset();}
bool Tracker::reset_after_contact(const WorldObservation& previous,const WorldObservation& current,bool flight,std::string& reason){
    const double dt=(current.stamp.sample_time_ns-previous.stamp.sample_time_ns)*1e-9;
    if(!valid_observation(previous,previous.stamp)||!valid_observation(current,current.stamp)||!versions(previous.stamp,current.stamp)||current.stamp.pair_id<=previous.stamp.pair_id||dt<=0||dt>.08||cv::norm(current.world-previous.world)/dt>15){reason="invalid_contact_reset_observations";return false;}
    auto velocity=(current.world-previous.world)/dt;if(flight)velocity[2]-=.5*cfg_.gravity*dt;
    clear();state_=cv::Mat::zeros(6,1,CV_64F);covariance_=cv::Mat::eye(6,6,CV_64F);cv::Mat(current.covariance).copyTo(covariance_(cv::Rect(0,0,3,3)));
    for(int i=0;i<3;++i){state_.at<double>(i)=current.world[i];state_.at<double>(i+3)=velocity[i];}
    last_=last_observed_=current.stamp;last_observed_position_=current.world;initialized_=true;last_flight_=flight;reason="contact_velocity_reset";return true;
}
std::optional<cv::Vec3d> Tracker::predict(const FrameStamp& s,bool flight) const {
    if(!initialized_||!versions(last_,s)||s.sample_time_ns<=last_.sample_time_ns||s.pair_id<=last_.pair_id)return std::nullopt;
    const double dt=(s.sample_time_ns-last_.sample_time_ns)*1e-9,age=(s.sample_time_ns-last_observed_.sample_time_ns)*1e-9;
    if(dt>cfg_.max_gap_s||age>cfg_.max_gap_s)return std::nullopt;
    return first3(transition(dt)*state_+gravity(dt,cfg_.gravity,flight));
}
std::optional<ball::PredictionHint> Tracker::roi_hint(const FrameStamp& s,Eye eye,const Calibration& c,bool flight,float diameter) const {
    if(s.calibration_version!=c.version||!std::isfinite(diameter)||diameter<0||diameter>44||(eye!=Eye::Left&&eye!=Eye::Right))return std::nullopt;
    auto w=predict(s,flight);if(!w)return std::nullopt;auto p=project(*w,eye,c);if(!p)return std::nullopt;
    ball::PredictionHint h;h.target=s;h.target.eye=eye;h.source_pair_id=last_observed_.pair_id;h.source_sample_time_ns=last_observed_.sample_time_ns;h.image_center=cv::Point2f(*p);h.previous_diameter_px=diameter;h.predictor_version="b-kalman-v1-draft";return h;
}
TrackResult Tracker::update(const FrameStamp& s,const std::optional<WorldObservation>& measurement,bool flight){
    TrackResult out;out.stamp=s;
    if(!std::isfinite(cfg_.gravity)||cfg_.gravity<=0||!std::isfinite(cfg_.max_gap_s)||cfg_.max_gap_s<=0||!std::isfinite(cfg_.gate_squared)||cfg_.gate_squared<=0||!std::isfinite(cfg_.acceleration_noise)||cfg_.acceleration_noise<0||!std::isfinite(cfg_.initial_velocity_variance)||cfg_.initial_velocity_variance<=0){out.reason="invalid_track_config";return out;}
    if(s.sample_time_ns<0||s.mode_id.empty()||s.config_version.empty()||s.calibration_version.empty()){out.reason="missing_track_metadata";return out;}
    const bool valid=measurement&&valid_observation(*measurement,s);
    if(measurement&&!valid){out.reason="invalid_track_observation";return out;}
    if(valid)out.raw_observed=measurement->world;
    if(initialized_&&!versions(last_,s)){clear();out.reset=true;out.reason="configuration_reset";}
    if(initialized_&&(s.sample_time_ns<=last_.sample_time_ns||s.pair_id<=last_.pair_id)){out.reason="nonmonotonic_sample";return out;}
    if(initialized_){out.dt=(s.sample_time_ns-last_.sample_time_ns)*1e-9;const double age=(s.sample_time_ns-last_observed_.sample_time_ns)*1e-9;if(out.dt>cfg_.max_gap_s||age>cfg_.max_gap_s){clear();out.reset=true;out.reason="gap_reset";}}
    if(!initialized_){if(!valid){out.reason=out.reset?"gap_reset_no_observation":"uninitialized";return out;}state_=cv::Mat::zeros(6,1,CV_64F);for(int i=0;i<3;++i)state_.at<double>(i)=measurement->world[i];covariance_=cv::Mat::eye(6,6,CV_64F)*cfg_.initial_velocity_variance;cv::Mat(measurement->covariance).copyTo(covariance_(cv::Rect(0,0,3,3)));last_=last_observed_=s;last_observed_position_=measurement->world;last_flight_=flight;initialized_=true;out.filtered=measurement->world;out.velocity=cv::Vec3d();out.accepted=true;if(out.reason.empty())out.reason="initialized";return out;}
    if(valid&&flight&&!last_flight_&&last_observed_.pair_id==last_.pair_id){
        // A held ball has near-zero velocity. Enter flight using the actual
        // first measured displacement, instead of gating the launch impulse.
        auto v=(measurement->world-last_observed_position_)/out.dt;v[2]+=.5*cfg_.gravity*out.dt;
        for(int i=0;i<3;++i){state_.at<double>(i+3)=v[i];covariance_.at<double>(i+3,i+3)=1;}
        out.reason="flight_transition";
    }
    last_flight_=flight;
    const double dt=out.dt;cv::Mat f=transition(dt),prior=f*state_+gravity(dt,cfg_.gravity,flight),q=cv::Mat::zeros(6,6,CV_64F);
    const double a2=cfg_.acceleration_noise*cfg_.acceleration_noise;for(int i=0;i<3;++i){q.at<double>(i,i)=a2*std::pow(dt,4)/4;q.at<double>(i,i+3)=q.at<double>(i+3,i)=a2*std::pow(dt,3)/2;q.at<double>(i+3,i+3)=a2*dt*dt;}
    cv::Mat prior_cov=f*covariance_*f.t()+q;out.predicted=first3(prior);state_=prior;covariance_=prior_cov;last_=s;
    if(valid){cv::Mat h=cv::Mat::zeros(3,6,CV_64F);for(int i=0;i<3;++i)h.at<double>(i,i)=1;cv::Mat noise=cv::Mat(measurement->covariance).clone(),innovation=cv::Mat(measurement->world)-h*prior,sc=h*prior_cov*h.t()+noise,inv;
        cv::invert(sc,inv,cv::DECOMP_SVD);cv::Mat d=innovation.t()*inv*innovation;out.innovation_squared=d.at<double>(0);
        if(out.innovation_squared<=cfg_.gate_squared){cv::Mat gain=prior_cov*h.t()*inv;state_=prior+gain*innovation;cv::Mat j=cv::Mat::eye(6,6,CV_64F)-gain*h;covariance_=j*prior_cov*j.t()+gain*noise*gain.t();last_observed_=s;last_observed_position_=measurement->world;rejected_streak_=0;last_rejected_position_.reset();out.filtered=first3(state_);out.accepted=true;if(out.reason.empty())out.reason="updated";}
        else{
            out.reason="outlier_rejected";const double rejected_dt=last_rejected_position_?(s.sample_time_ns-last_rejected_time_)*1e-9:0;
            const bool coherent=last_rejected_position_&&rejected_dt>0&&rejected_dt<=.08&&cv::norm(measurement->world-*last_rejected_position_)/rejected_dt<15;
            rejected_streak_=coherent?rejected_streak_+1:1;
            if(rejected_streak_>=3){auto velocity=(measurement->world-*last_rejected_position_)/rejected_dt;if(flight)velocity[2]-=.5*cfg_.gravity*rejected_dt;
                for(int i=0;i<3;++i){state_.at<double>(i)=measurement->world[i];state_.at<double>(i+3)=velocity[i];}
                covariance_=cv::Mat::eye(6,6,CV_64F);noise.copyTo(covariance_(cv::Rect(0,0,3,3)));last_observed_=s;last_observed_position_=measurement->world;out.filtered=measurement->world;out.accepted=true;out.reset=true;out.reason="reacquired_after_three_observations";rejected_streak_=0;
            }
            last_rejected_position_=measurement->world;last_rejected_time_=s.sample_time_ns;
        }
    }else out.reason="prediction_only";
    out.velocity=first3(state_,3);return out;
}
} // namespace
