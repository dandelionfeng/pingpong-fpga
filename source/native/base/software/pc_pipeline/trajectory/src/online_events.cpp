#include "trajectory.hpp"
#include <algorithm>
#include <cmath>
#include <sstream>
#include <stdexcept>

namespace pingpong::trajectory {
namespace {
bool identity(const FrameStamp& a,const FrameStamp& b){return a.pair_id==b.pair_id&&a.sample_time_ns==b.sample_time_ns&&a.mode_id==b.mode_id&&a.config_version==b.config_version&&a.calibration_version==b.calibration_version;}
bool version(const FrameStamp& a,const FrameStamp& b){return a.mode_id==b.mode_id&&a.config_version==b.config_version&&a.calibration_version==b.calibration_version;}
double distance(cv::Point2d p,cv::Rect2d b){return std::hypot(std::max({b.x-p.x,0.,p.x-b.x-b.width}),std::max({b.y-p.y,0.,p.y-b.y-b.height}));}
std::string signature(const EventResult& r){std::ostringstream s;s.precision(12);s<<r.status<<r.reason;for(auto t:{r.release,r.apex,r.contact})if(t)s<<t->begin_ns<<':'<<t->end_ns;s<<r.fit.valid;if(r.fit.valid)s<<r.fit.height_m<<r.fit.used_pair_ids.size();return s.str();}
bool same_detection(const SemanticDetection& a,const SemanticDetection& b){return identity(a.source,b.source)&&a.source.eye==b.source.eye&&a.label==b.label&&a.model_version==b.model_version&&a.box==b.box;}
}
OnlineEvents::OnlineEvents(EventConfig event,OnlineConfig online):cfg_(event),online_(online){
    if(!std::isfinite(event.max_detection_latency_s)||event.max_detection_latency_s<0||!std::isfinite(event.min_score)||event.min_score<0||event.min_score>1||!std::isfinite(event.near_px)||event.near_px<0||!std::isfinite(event.rise_m_s)||event.rise_m_s<=0||!std::isfinite(event.contact_velocity_change)||event.contact_velocity_change<=0||!std::isfinite(event.max_observation_gap_s)||event.max_observation_gap_s<=0)throw std::invalid_argument("invalid_event_config");
    if(online_.max_frames<6||online_.max_detections<2||online_.max_pending_detections<1||!std::isfinite(online_.max_event_s)||online_.max_event_s<=0||!std::isfinite(online_.settle_s)||online_.settle_s<event.max_detection_latency_s||online_.restart_holding_frames<3||std::size_t(online_.restart_holding_frames)>=online_.max_frames)throw std::invalid_argument("invalid_online_config");
}
void OnlineEvents::recompute(std::int64_t now,const std::string& trigger,bool final){
    if(frames_.empty())return;
    current_=analyze_events(frames_,detections_,cfg_);
    if(final&&(trigger=="configuration_reset"||trigger=="time_gap_reset"||trigger=="frame_capacity"||trigger=="stream_nonmonotonic")){
        current_.status="unknown";current_.reason=trigger;current_.contact.reset();current_.fit.valid=false;current_.fit.reason=trigger;
    }
    const auto key=signature(current_);if(!final&&key==signature_)return;signature_=key;
    if(updates_.size()>=64){updates_.erase(updates_.begin());++stats_.queue_overflows;}
    updates_.push_back({event_id_,++revision_,now,final,trigger,current_,frames_});
}
void OnlineEvents::close(std::int64_t now,const std::string& trigger){recompute(now,trigger,true);frames_.clear();detections_.clear();pending_.clear();current_=EventResult{};signature_.clear();revision_=0;++event_id_;}
bool OnlineEvents::holding(const EventFrame& f)const{
    if(!f.observed)return false;
    for(const auto& d:detections_){const auto p=d.source.eye==Eye::Left?f.left_ball:f.right_ball;if(identity(d.source,f.stamp)&&d.label=="hand"&&p&&distance(*p,d.box)<=cfg_.near_px)return true;}return false;
}
bool OnlineEvents::push_frame(const EventFrame& f,std::int64_t now,std::string& reason){
    if(now<now_||now<f.stamp.sample_time_ns||f.stamp.sample_time_ns<0||(f.stamp.eye!=Eye::Left&&f.stamp.eye!=Eye::Right)||f.stamp.mode_id.empty()||f.stamp.config_version.empty()||f.stamp.calibration_version.empty()||(f.observed&&(!cv::checkRange(cv::Mat(*f.observed))||!std::isfinite(f.weight)||f.weight<=0))){reason="invalid_online_frame_or_clock";return false;}
    if(!frames_.empty()){
        const auto& last=frames_.back().stamp;
        if(f.stamp.sample_time_ns<=last.sample_time_ns||f.stamp.pair_id<=last.pair_id){++stats_.resets;close(now,"stream_nonmonotonic");reason="nonmonotonic_sample";return false;}
        if(!version(f.stamp,last)){++stats_.resets;close(now,"configuration_reset");}
        else if((f.stamp.sample_time_ns-last.sample_time_ns)*1e-9>.25){++stats_.resets;close(now,"time_gap_reset");}
    }
    if(frames_.size()>=online_.max_frames){++stats_.queue_overflows;close(now,"frame_capacity");}
    now_=now;frames_.push_back(f);stats_.peak_frames=std::max(stats_.peak_frames,frames_.size());
    for(auto i=pending_.begin();i!=pending_.end();){
        if(i->source.pair_id==f.stamp.pair_id){if(identity(i->source,f.stamp))detections_.push_back(*i);else ++stats_.rejected_detections;i=pending_.erase(i);}
        else if(i->source.pair_id<f.stamp.pair_id){++stats_.expired_detections;i=pending_.erase(i);}else ++i;
    }
    recompute(now,"frame");advance(now);reason="ok";return true;
}
bool OnlineEvents::push_detection(const SemanticDetection& d,std::int64_t arrival,std::string& reason){
    const double age=(arrival-d.source.sample_time_ns)*1e-9;
    if(arrival<now_||arrival<d.completed_time_ns||d.completed_time_ns<d.source.sample_time_ns||age<0||age>cfg_.max_detection_latency_s||d.source.sample_time_ns<0||d.source.mode_id.empty()||d.source.config_version.empty()||d.source.calibration_version.empty()||(d.source.eye!=Eye::Left&&d.source.eye!=Eye::Right)||d.model_version.empty()||!d.visible||!std::isfinite(d.score)||d.score<cfg_.min_score||d.score>1||!std::isfinite(d.box.x)||!std::isfinite(d.box.y)||!std::isfinite(d.box.width)||!std::isfinite(d.box.height)||d.box.width<=0||d.box.height<=0||(d.label!="hand"&&d.label!="racket")){
        ++stats_.rejected_detections;reason=age>cfg_.max_detection_latency_s?"expired_detection_arrival":"invalid_detection_or_clock";return false;
    }
    now_=arrival;
    for(const auto& set:{&detections_,&pending_})for(const auto& old:*set)if(same_detection(old,d)){++stats_.duplicate_detections;reason="duplicate_detection";return false;}
    const auto it=std::find_if(frames_.begin(),frames_.end(),[&](const auto& f){return f.stamp.pair_id==d.source.pair_id;});
    if(it!=frames_.end()){
        if(!identity(it->stamp,d.source)){++stats_.rejected_detections;reason="detection_source_identity";return false;}
        if(detections_.size()+pending_.size()>=online_.max_detections){++stats_.queue_overflows;reason="detection_capacity";return false;}
        detections_.push_back(d);recompute(arrival,"late_detection");
    }else{
        if(!frames_.empty()&&d.source.pair_id<=frames_.back().stamp.pair_id){++stats_.expired_detections;reason="source_frame_unavailable";return false;}
        if(pending_.size()>=online_.max_pending_detections||detections_.size()+pending_.size()>=online_.max_detections){++stats_.queue_overflows;reason="pending_capacity";return false;}
        pending_.push_back(d);
    }
    stats_.peak_detections=std::max(stats_.peak_detections,buffered_detections());advance(arrival);reason="ok";return true;
}
void OnlineEvents::advance(std::int64_t now){
    if(now<now_)return;now_=now;
    for(auto i=pending_.begin();i!=pending_.end();)if((now-i->source.sample_time_ns)*1e-9>cfg_.max_detection_latency_s){++stats_.expired_detections;i=pending_.erase(i);}else ++i;
    if(frames_.empty())return;
    // A stable held ball starts another attempt. Preserve the initial holding
    // frames for its release, while finalizing the preceding event first.
    const std::size_t count=std::size_t(online_.restart_holding_frames);
    if(current_.release&&frames_.size()>count){
        const std::size_t start=frames_.size()-count;bool stable=true;
        for(std::size_t i=start;i<frames_.size();++i){if(!holding(frames_[i]))stable=false;if(i>start){const double dt=(frames_[i].stamp.sample_time_ns-frames_[i-1].stamp.sample_time_ns)*1e-9;if(!frames_[i].observed||!frames_[i-1].observed||dt<=0||dt>cfg_.max_observation_gap_s||cv::norm(*frames_[i].observed-*frames_[i-1].observed)/dt>cfg_.rise_m_s)stable=false;}}
        if(stable){std::vector<EventFrame>keep(frames_.begin()+start,frames_.end());std::vector<SemanticDetection>sem;for(const auto& d:detections_)if(d.source.pair_id>=keep.front().stamp.pair_id)sem.push_back(d);
            close(now,"next_holding_attempt");frames_=std::move(keep);detections_=std::move(sem);recompute(now,"restart_holding");return;}
    }
    if(current_.contact&&(now-current_.contact->end_ns)*1e-9>=online_.settle_s){close(now,"contact_settled");return;}
    if((now-frames_.front().stamp.sample_time_ns)*1e-9>=online_.max_event_s)close(now,"event_timeout");
}
void OnlineEvents::finish(std::int64_t now){if(now<now_)throw std::invalid_argument("online_finish_clock");now_=now;close(now,"end_of_stream");}
std::vector<EventUpdate> OnlineEvents::take_updates(){auto result=std::move(updates_);updates_.clear();return result;}
} // namespace
