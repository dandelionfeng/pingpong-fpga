#include "trajectory.hpp"
#include <algorithm>
#include <cmath>
#include <map>

namespace pingpong::trajectory {
namespace {
double seconds(std::int64_t a,std::int64_t b){return (a-b)*1e-9;}
cv::Vec3d evaluate(const FlightFit& f,double t){return {f.x[0]+f.x[1]*t,f.y[0]+f.y[1]*t,f.z[0]+f.z[1]*t+f.z[2]*t*t};}
bool solve(const std::vector<FitSample>& samples,const std::vector<double>& weights,std::int64_t origin,int axis,int degree,cv::Mat& coefficients){
    cv::Mat a(int(samples.size()),degree+1,CV_64F),b(int(samples.size()),1,CV_64F);for(int i=0;i<int(samples.size());++i){const double t=seconds(samples[i].time_ns,origin),w=std::sqrt(weights[i]);a.at<double>(i,0)=w;a.at<double>(i,1)=w*t;if(degree==2)a.at<double>(i,2)=w*t*t;b.at<double>(i)=w*samples[i].world[axis];}return cv::solve(a,b,coefficients,cv::DECOMP_SVD);
}
double median(std::vector<double> v){auto m=v.begin()+v.size()/2;std::nth_element(v.begin(),m,v.end());return *m;}
double box_distance(cv::Point2d p,cv::Rect2d b){const double dx=std::max({b.x-p.x,0.0,p.x-b.x-b.width}),dy=std::max({b.y-p.y,0.0,p.y-b.y-b.height});return std::hypot(dx,dy);}
}
FlightFit fit_flight(const std::vector<FitSample>& input,TimeInterval release,const std::optional<cv::Vec3d>& held,double held_sigma,bool diagnostic_relaxed){
    FlightFit f;if(release.begin_ns<0||release.end_ns<release.begin_ns){f.reason="invalid_release_interval";return f;}
    if(!std::isfinite(held_sigma)||held_sigma<0){f.reason="invalid_held_uncertainty";return f;}
    std::vector<FitSample>s;for(const auto& p:input)if(p.observed&&p.time_ns>=release.begin_ns&&p.weight>0&&std::isfinite(p.weight)&&cv::checkRange(cv::Mat(p.world)))s.push_back(p);
    if(s.size()<6){f.reason="insufficient_actual_observations";return f;}
    for(std::size_t i=1;i<s.size();++i)if(s[i].time_ns<=s[i-1].time_ns||s[i].pair_id<=s[i-1].pair_id){f.reason="nonmonotonic_fit_samples";return f;}
    f.origin_ns=release.begin_ns+(release.end_ns-release.begin_ns)/2;if(seconds(s.back().time_ns,s.front().time_ns)<0.08){f.reason="insufficient_time_span";return f;}
    std::vector<double>w;for(const auto& p:s)w.push_back(std::min(p.weight,1e6));
    for(int iteration=0;iteration<8;++iteration){cv::Mat x,y,z;if(!solve(s,w,f.origin_ns,0,1,x)||!solve(s,w,f.origin_ns,1,1,y)||!solve(s,w,f.origin_ns,2,2,z)){f.reason="fit_solve_failed";return f;}f.x={x.at<double>(0),x.at<double>(1)};f.y={y.at<double>(0),y.at<double>(1)};f.z={z.at<double>(0),z.at<double>(1),z.at<double>(2)};
        std::vector<double>res;for(const auto& p:s)res.push_back(cv::norm(evaluate(f,seconds(p.time_ns,f.origin_ns))-p.world));const double scale=std::max(1e-5,1.4826*median(res));for(std::size_t i=0;i<s.size();++i)w[i]=std::min(s[i].weight,1e6)*std::min(1.0,1.5*scale/std::max(res[i],1e-12));}
    if(!std::isfinite(f.z[2])||f.z[2]>=-0.1){f.reason="not_concave_flight";return f;}
    f.apex_s=-f.z[1]/(2*f.z[2]);const double first=seconds(s.front().time_ns,f.origin_ns),last=seconds(s.back().time_ns,f.origin_ns);
    if(f.apex_s<=std::max(0.0,first)||f.apex_s>=last){f.reason="apex_not_bracketed_by_observations";return f;}
    double sum=0,weight=0;for(std::size_t i=0;i<s.size();++i){const double e=cv::norm(evaluate(f,seconds(s[i].time_ns,f.origin_ns))-s[i].world);sum+=w[i]*e*e;weight+=w[i];f.used_pair_ids.push_back(s[i].pair_id);}f.residual_rms_m=std::sqrt(sum/weight);
    if(!diagnostic_relaxed&&f.residual_rms_m>0.03){f.reason="fit_residual_high";return f;}
    double sigma=0;for(const auto& p:s)sigma=std::max(sigma,std::sqrt(1/p.weight));f.measurement_sigma_m=sigma;
    if(held&&cv::checkRange(cv::Mat(*held))){const double a=f.z[2],b=f.z[1],cc=f.z[0]-(*held)[2],disc=b*b-4*a*cc;if(disc>=0){for(double t:{(-b+std::sqrt(disc))/(2*a),(-b-std::sqrt(disc))/(2*a)}){
        const double lo=seconds(release.begin_ns,f.origin_ns),hi=seconds(release.end_ns,f.origin_ns);
        if(f.z[1]+2*f.z[2]*t<=0)continue;
        if(t>=lo-1e-6&&t<=hi+1e-6){f.release_offset_s=std::clamp(t,lo,hi);f.release_refined=true;f.release_method="held_height_intersection";break;}
        const double constrained=std::clamp(t,lo,hi);
        // A tiny noisy root outside the observed interval must not force an
        // arbitrary midpoint. Clamp only within one interval width and within
        // the declared held/observation error budget; never extrapolate time.
        if(hi>lo&&std::abs(t-constrained)<=hi-lo&&std::abs(evaluate(f,constrained)[2]-(*held)[2])<=2*(sigma+held_sigma)){f.release_offset_s=constrained;f.release_refined=true;f.release_method="held_height_constrained_with_declared_noise";break;}
    }}}
    f.release_world=evaluate(f,f.release_offset_s);f.apex_world=evaluate(f,f.apex_s);f.height_m=f.apex_world[2]-f.release_world[2];if(f.height_m<=0){f.reason="nonpositive_height";return f;}
    const double z0=evaluate(f,seconds(release.begin_ns,f.origin_ns))[2],z1=evaluate(f,seconds(release.end_ns,f.origin_ns))[2];
    // Include declared observation scale as well as timing and residual. This
    // deliberately remains an error budget envelope, not a calibrated CI.
    const double margin=2*(f.residual_rms_m+sigma+held_sigma);
    f.height_low_m=std::max(0.0,f.apex_world[2]-std::max(z0,z1)-margin);f.height_high_m=f.apex_world[2]-std::min(z0,z1)+margin;
    auto d=f.apex_world-f.release_world;f.chord_angle_deg=std::atan2(std::hypot(d[0],d[1]),d[2])*180/CV_PI;f.velocity_angle_deg=std::atan2(std::hypot(f.x[1],f.y[1]),f.z[1]+2*f.z[2]*f.release_offset_s)*180/CV_PI;f.valid=true;f.reason="ok";return f;
}
EventResult analyze_events(const std::vector<EventFrame>& frames,const std::vector<SemanticDetection>& detections,const EventConfig& cfg){
    EventResult out;out.states.resize(frames.size(),"unknown");if(frames.size()<3){out.reason="insufficient_event_frames";return out;}
    if(!std::isfinite(cfg.min_score)||!std::isfinite(cfg.near_px)||!std::isfinite(cfg.rise_m_s)||!std::isfinite(cfg.contact_velocity_change)||!std::isfinite(cfg.max_observation_gap_s)||!std::isfinite(cfg.max_detection_latency_s)||cfg.min_score<0||cfg.min_score>1||cfg.near_px<0||cfg.rise_m_s<=0||cfg.contact_velocity_change<=0||cfg.max_observation_gap_s<=0||cfg.max_detection_latency_s<0){out.reason="invalid_event_config";return out;}
    std::map<std::uint64_t,std::size_t> index;for(std::size_t i=0;i<frames.size();++i){const auto& s=frames[i].stamp;if(s.sample_time_ns<0||s.mode_id.empty()||s.config_version.empty()||s.calibration_version.empty()||(frames[i].observed&&(!cv::checkRange(cv::Mat(*frames[i].observed))||!std::isfinite(frames[i].weight)||frames[i].weight<=0))||(i&&(s.sample_time_ns<=frames[i-1].stamp.sample_time_ns||s.pair_id<=frames[i-1].stamp.pair_id||s.mode_id!=frames[0].stamp.mode_id||s.config_version!=frames[0].stamp.config_version||s.calibration_version!=frames[0].stamp.calibration_version))){out.reason="event_frame_identity_or_time";return out;}index[s.pair_id]=i;}
    std::vector<bool>hand(frames.size(),false),racket(frames.size(),false),hand_known(frames.size(),false);
    for(const auto& d:detections){auto it=index.find(d.source.pair_id);if(it==index.end()){++out.ignored_detections;continue;}const auto& frame=frames[it->second];const auto& s=frame.stamp;const auto p=d.source.eye==Eye::Left?frame.left_ball:frame.right_ball;
        if(!p||(d.source.eye!=Eye::Left&&d.source.eye!=Eye::Right)||!std::isfinite(p->x)||!std::isfinite(p->y)||d.source.sample_time_ns!=s.sample_time_ns||d.source.mode_id!=s.mode_id||d.source.config_version!=s.config_version||d.source.calibration_version!=s.calibration_version||d.completed_time_ns<d.source.sample_time_ns||seconds(d.completed_time_ns,d.source.sample_time_ns)>cfg.max_detection_latency_s||d.model_version.empty()||!d.visible||!std::isfinite(d.score)||d.score<cfg.min_score||d.score>1||!std::isfinite(d.box.x)||!std::isfinite(d.box.y)||!std::isfinite(d.box.width)||!std::isfinite(d.box.height)||d.box.width<=0||d.box.height<=0||(d.label!="hand"&&d.label!="racket")){++out.ignored_detections;continue;}
        ++out.associated_detections;const bool near=box_distance(*p,d.box)<=cfg.near_px;if(d.label=="hand"){hand_known[it->second]=true;hand[it->second]=hand[it->second]||near;}else racket[it->second]=racket[it->second]||near;}
    std::optional<std::size_t>last_hand,release_i,apex_i,last_rising_i;bool held=false,recaught=false;
    for(std::size_t i=0;i<frames.size();++i){if(!frames[i].observed)continue;
        if(!release_i){if(hand[i]){last_hand=i;held=true;out.states[i]="holding";}
            if(i>0&&last_hand&&hand_known[i]&&!hand[i]&&frames[i-1].observed&&i+1<frames.size()&&frames[i+1].observed){const double dt=seconds(frames[i].stamp.sample_time_ns,frames[i-1].stamp.sample_time_ns),nextdt=seconds(frames[i+1].stamp.sample_time_ns,frames[i].stamp.sample_time_ns);const double vz=((*frames[i].observed)[2]-(*frames[i-1].observed)[2])/dt,vnext=((*frames[i+1].observed)[2]-(*frames[i].observed)[2])/nextdt;
                if(dt<=cfg.max_observation_gap_s&&nextdt<=cfg.max_observation_gap_s&&seconds(frames[i].stamp.sample_time_ns,frames[*last_hand].stamp.sample_time_ns)<=cfg.max_observation_gap_s&&vz>cfg.rise_m_s&&vnext>cfg.rise_m_s){release_i=i;out.release=TimeInterval{frames[*last_hand].stamp.sample_time_ns,frames[i].stamp.sample_time_ns};out.states[i]="rising";}}continue;}
        if(i==0||!frames[i-1].observed){out.states[i]="flight_gap";continue;}
        const double dt=seconds(frames[i].stamp.sample_time_ns,frames[i-1].stamp.sample_time_ns);if(dt>cfg.max_observation_gap_s){out.states[i]="flight_gap";continue;}
        const cv::Vec3d velocity=(*frames[i].observed-*frames[i-1].observed)/dt;
        if(velocity[2]>0)last_rising_i=i;
        if(!apex_i&&last_rising_i&&velocity[2]<=0){apex_i=i;out.apex=TimeInterval{frames[*last_rising_i>0?*last_rising_i-1:0].stamp.sample_time_ns,frames[i].stamp.sample_time_ns};}
        out.states[i]=apex_i?"falling":"rising";
        if(apex_i&&hand[i]&&i+1<frames.size()&&hand[i+1]&&frames[i+1].observed&&seconds(frames[i+1].stamp.sample_time_ns,frames[i].stamp.sample_time_ns)<=cfg.max_observation_gap_s&&cv::norm(*frames[i+1].observed-*frames[i].observed)/seconds(frames[i+1].stamp.sample_time_ns,frames[i].stamp.sample_time_ns)<cfg.rise_m_s){recaught=true;out.states[i]="recaught";break;}
        if(apex_i&&racket[i-1]&&i>=3&&i+1<frames.size()&&frames[i-3].observed&&frames[i+1].observed){
            const double before_dt=seconds(frames[i-1].stamp.sample_time_ns,frames[i-3].stamp.sample_time_ns),after_dt=seconds(frames[i+1].stamp.sample_time_ns,frames[i-1].stamp.sample_time_ns);
            if(before_dt>0&&after_dt>0&&before_dt<=2*cfg.max_observation_gap_s&&after_dt<=2*cfg.max_observation_gap_s){
                const auto before=(*frames[i-1].observed-*frames[i-3].observed)/before_dt,after=(*frames[i+1].observed-*frames[i-1].observed)/after_dt;
                const double quality_noise=std::sqrt(1/std::max(1.0,frames[i-1].weight))/std::min(before_dt,after_dt);
                if(cv::norm(after-before)>cfg.contact_velocity_change+2*quality_noise){out.contact=TimeInterval{frames[i-1].stamp.sample_time_ns,frames[i].stamp.sample_time_ns};out.states[i]="contact";break;}
            }
        }
    }
    if(!out.release){bool continuous_hold=held;for(std::size_t i=0;i<frames.size();++i)if(!frames[i].observed||!hand[i])continuous_hold=false;out.status=continuous_hold?"cancelled":"unknown";out.reason=continuous_hold?"no_release_evidence":"hand_or_release_evidence_missing";return out;}
    // Confirm a velocity break across a short measurement gap using actual
    // observations on both sides and a source-frame racket observation. The
    // interval spans the available neighboring points; it is never narrowed
    // with a prediction or completion timestamp.
    if(apex_i&&!recaught){
        for(std::size_t k=*apex_i;k+1<frames.size();++k){if(!racket[k]||!frames[k].observed)continue;
            std::vector<std::size_t>before,after;for(std::size_t j=k;j>0&&before.size()<2;){--j;if(frames[j].observed)before.push_back(j);}for(std::size_t j=k+1;j<frames.size()&&after.size()<2;++j)if(frames[j].observed)after.push_back(j);
            if(before.size()<2||after.size()<2)continue;
            const auto b=before.back(),a=after.back();const double dtb=seconds(frames[k].stamp.sample_time_ns,frames[b].stamp.sample_time_ns),dta=seconds(frames[a].stamp.sample_time_ns,frames[k].stamp.sample_time_ns);
            if(dtb<=0||dta<=0||dtb>2*cfg.max_observation_gap_s||dta>2*cfg.max_observation_gap_s)continue;
            const auto vb=(*frames[k].observed-*frames[b].observed)/dtb,va=(*frames[a].observed-*frames[k].observed)/dta;
            const double sigma=std::sqrt(1/std::max(1.,frames[k].weight));
            if(cv::norm(va-vb)>cfg.contact_velocity_change+2*sigma/std::min(dtb,dta)){if(!out.contact||frames[k].stamp.sample_time_ns<out.contact->begin_ns){out.contact=TimeInterval{frames[k].stamp.sample_time_ns,frames[after.front()].stamp.sample_time_ns};out.states[after.front()]="contact";}break;}
        }
    }
    std::vector<FitSample> samples;std::int64_t end=out.contact?out.contact->begin_ns:frames.back().stamp.sample_time_ns;
    // Missing contact does not authorize fitting a later stroke or another
    // appearance of the ball across an observation gap. Keep the first flight.
    if(cfg.diagnostic_relaxed && !out.contact) for(std::size_t i=1;i<frames.size();++i)
      if(frames[i-1].stamp.sample_time_ns>=out.release->end_ns &&
         seconds(frames[i].stamp.sample_time_ns,frames[i-1].stamp.sample_time_ns)>cfg.max_observation_gap_s) {
        end=frames[i-1].stamp.sample_time_ns;break;
      }
    // Toss metrics need the first apex and the release plane. Limit the
    // free-flight fit to a local, actually observed apex neighborhood. A
    // missed racket box must not allow the later stroke to pull the fitted
    // release height, apex or horizontal velocity away from the toss.
    if(apex_i) {
        std::size_t supported=0;
        for(std::size_t j=*apex_i;j<frames.size();++j) {
            if(j>*apex_i && frames[j].observed && frames[j].fit_eligible) ++supported;
            if(supported>=4) { end=std::min(end,frames[j].stamp.sample_time_ns);break; }
        }
    }
    for(const auto& f:frames)if(f.observed&&f.fit_eligible&&f.stamp.sample_time_ns>=out.release->end_ns&&f.stamp.sample_time_ns<=end)samples.push_back({f.stamp.pair_id,f.stamp.sample_time_ns,*f.observed,f.weight,true});
    for(std::size_t i=1;i<frames.size();++i)if(frames[i].stamp.sample_time_ns>=out.release->end_ns&&frames[i].stamp.sample_time_ns<=end&&seconds(frames[i].stamp.sample_time_ns,frames[i-1].stamp.sample_time_ns)>.25){out.status="unknown";out.reason="event_time_gap";return out;}
    out.fit=fit_flight(samples,*out.release,last_hand?frames[*last_hand].observed:std::nullopt,last_hand?std::sqrt(1/frames[*last_hand].weight):0,cfg.diagnostic_relaxed);
    if(out.fit.valid){const auto at=out.fit.origin_ns+static_cast<std::int64_t>(std::llround(out.fit.apex_s*1e9));for(std::size_t i=1;i<frames.size();++i)if(frames[i-1].observed&&frames[i].observed&&frames[i-1].stamp.sample_time_ns<=at&&frames[i].stamp.sample_time_ns>=at&&seconds(frames[i].stamp.sample_time_ns,frames[i-1].stamp.sample_time_ns)<=cfg.max_observation_gap_s){out.apex=TimeInterval{frames[i-1].stamp.sample_time_ns,frames[i].stamp.sample_time_ns};break;}}
    if(recaught){out.status="cancelled";out.reason="observed_recatch_without_racket_contact";out.contact.reset();}
    else if(out.contact&&out.fit.valid){out.status="complete";out.reason="observed_events_and_fit";}
    else{out.status="unknown";out.reason=out.fit.valid?"contact_evidence_missing":out.fit.reason;}
    return out;
}
} // namespace
