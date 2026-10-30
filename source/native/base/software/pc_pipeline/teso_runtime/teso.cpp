#include "teso.hpp"
#include <opencv2/imgproc.hpp>
#include <numeric>
#ifdef __linux__
#include <sched.h>
#endif
namespace pipeline::teso {
namespace {
const M3 D(1,0,0,0,1,0,0,0,0);
M3 m3(const Json&j){M3 m;for(int r=0;r<3;++r)for(int c=0;c<3;++c)m(r,c)=j[r][c].get<double>();return m;}
cv::Mat distortion(const Json&j){cv::Mat d(1,int(j.size()),CV_64F);for(int i=0;i<d.cols;++i)d.at<double>(i)=j[i].get<double>();return d;}
Json array(const cv::Mat&m){Json a=Json::array();for(int r=0;r<m.rows;++r){Json row=Json::array();for(int c=0;c<m.cols;++c)row.push_back(m.at<double>(r,c));a.push_back(row);}return a;}
M3 cross(const cv::Vec3d&t){return {0,-t[2],t[1],t[2],0,-t[0],-t[1],t[0],0};}
M3 expSO3(const M3&w){cv::Vec3d a(w(2,1),w(0,2),w(1,0));M3 r;cv::Rodrigues(a,r);return r;}
double rotation(const M3&r){return std::acos(std::clamp((cv::trace(cv::Mat(r))[0]-1)*.5,-1.,1.))*180/CV_PI;}
std::vector<cv::Point2d> undistort(const std::vector<cv::Point2d>&p,const Json&c,int eye,bool pixels=false){std::vector<cv::Point2d> q;if(p.empty())return q;auto k=m3(c[eye?"K_right":"K_left"]);cv::undistortPoints(p,q,cv::Mat(k),distortion(c[eye?"D_right":"D_left"]),cv::noArray(),pixels?cv::Mat(k):cv::Mat());return q;}
cv::Vec3d normal(cv::Point2d p,const M3&k){return k.inv()*cv::Vec3d(p.x,p.y,1);}
double median(std::vector<double> v){if(v.empty())return INFINITY;std::sort(v.begin(),v.end());return v[v.size()/2];}
}
M3 Optimizer::omega1(const V5&x){double s=1/std::sqrt(2.);return M3(0,-x[2]*.5,x[1]*s,x[2]*.5,0,-x[0]*s,-x[1]*s,x[0]*s,0);}
M3 Optimizer::omega2(const V5&x){double s=1/std::sqrt(2.);return M3(0,x[2]*.5,x[4]*s,-x[2]*.5,0,-x[3]*s,-x[4]*s,x[3]*s,0);}
Optimizer::Optimizer(const M3&E,double sigma):sigma_(sigma){cv::Mat w,u,v;cv::SVD::compute(cv::Mat(E),w,u,v);u.copyTo(cv::Mat(U_,false));v.copyTo(cv::Mat(Vt_,false));if(cv::determinant(U_)<0)U_=-U_;if(cv::determinant(Vt_)<0)Vt_=-Vt_;}
M3 Optimizer::essential()const{return U_*D*Vt_;}
M3 Optimizer::derivative(int i)const{V5 x=V5::all(0);x[i]=1;return U_*(omega1(x)*D-D*omega2(x))*Vt_;}
std::pair<V5,V5> Optimizer::derivatives(const std::vector<Neighbors>&a,const std::vector<Neighbors>&b)const{
  V5 g=V5::all(0),h=V5::all(0);auto E=essential();double s2=sigma_*sigma_;
  std::array<M3,5> ds;for(int j=0;j<5;++j)ds[j]=derivative(j);
  // The exponential weight is shared across all five derivatives. Computing
  // it once per candidate preserves the author's equations and reduces cost.
  for(int reverse=0;reverse<2;++reverse){const auto &rows=reverse?b:a;auto e=reverse?E.t():E;std::array<M3,5> d;for(int j=0;j<5;++j)d[j]=reverse?ds[j].t():ds[j];
    for(const auto &row:rows){auto ex=e*row.x;std::array<cv::Vec3d,5> dx;for(int j=0;j<5;++j)dx[j]=d[j]*row.x;
      for(const auto &y:row.ys){double v=y.dot(ex),w=std::exp(-v*v/(2*s2)),gw=w*v/s2,hw=w*(1/s2-v*v/(s2*s2));for(int j=0;j<5;++j){double dv=y.dot(dx[j]);g[j]+=gw*dv;h[j]+=hw*dv*dv;}}}}
  for(int j=0;j<5;++j)h[j]=std::abs(h[j]);
  return {g,h};
}
V5 Optimizer::step(const std::vector<Neighbors>&a,const std::vector<Neighbors>&b){auto [g,h]=derivatives(a,b);V5 update=V5::all(0);for(int j=0;j<5;++j){double m=memory_[j];gradient_[j]=(m-1)/m*gradient_[j]+g[j]/m;variance_[j]=(m-1)/m*variance_[j]+g[j]*g[j]/m;hessian_[j]=(m-1)/m*hessian_[j]+h[j]/m;double lr=gradient_[j]*gradient_[j]/(variance_[j]+1e-7);
 if(burn_==1){memory_[j]=std::clamp((1-lr)*m+1,1.,10.);if(hessian_[j]>1e-12){double u=-lr*g[j]/hessian_[j];update[j]=std::abs(u)<=.0001875?u:u/(std::abs(u)+1e-7)*.0001875;}}
 else memory_[j]+=1;
 }if(burn_>1)--burn_;else{U_=U_*expSO3(omega1(update));Vt_=expSO3(-omega2(update))*Vt_;}return update;}
M3 essential(const Json&c){auto t=c.at("T_m").get<std::vector<double>>();return cross(cv::Vec3d(t[0],t[1],t[2]))*m3(c.at("R_left_to_right"));}
Json calibrationFromEssential(const Json&seed,const M3&E){cv::Mat r0,r1,t;cv::decomposeEssentialMat(cv::Mat(E),r0,r1,t);auto old=m3(seed["R_left_to_right"]);M3 a,b;r0.copyTo(cv::Mat(a,false));r1.copyTo(cv::Mat(b,false));auto r=rotation(a*old.t())<rotation(b*old.t())?a:b;auto original=seed["T_m"].get<std::vector<double>>();cv::Vec3d v=t;cv::Vec3d ref(original[0],original[1],original[2]);if(v.dot(ref)<0)v=-v;v*=cv::norm(ref)/cv::norm(v);
 cv::Mat rr0,rr1,p0,p1,q;cv::stereoRectify(cv::Mat(m3(seed["K_left"])),distortion(seed["D_left"]),cv::Mat(m3(seed["K_right"])),distortion(seed["D_right"]),{1280,720},cv::Mat(r),cv::Mat(v),rr0,rr1,p0,p1,q,cv::CALIB_ZERO_DISPARITY,0);
 Json out=seed;out["R_left_to_right"]=array(cv::Mat(r));out["T_m"]={v[0],v[1],v[2]};out["R1"]=array(rr0);out["R2"]=array(rr1);out["P1"]=array(p0);out["P2"]=array(p1);out["Q"]=array(q);out["stereo_rms_px"]=nullptr;out["stereo_rms_status"]="not_estimated_by_TESO";out["estimated_baseline_m"]=cv::norm(v);return out;}
double sampsonPixels(const M3&E,cv::Point2d a,cv::Point2d b,const Json&c){M3 f=m3(c["K_right"]).inv().t()*E*m3(c["K_left"]).inv();cv::Vec3d x(a.x,a.y,1),y(b.x,b.y,1);auto ex=f*x,ety=f.t()*y;double den=ex[0]*ex[0]+ex[1]*ex[1]+ety[0]*ety[0]+ety[1]*ety[1];return std::abs(y.dot(ex))/std::sqrt(std::max(den,1e-30));}
bool improves(double a,double b,double am,double bm){return std::isfinite(b)&&a-b>=std::max(.04,.03*a)&&bm<=am*1.02+.005;}
Online::Online(Json seed,Settings cfg):seed_(seed),active_(seed),cfg_(cfg){if(cfg.sample_stride<1||cfg.features<80||cfg.features>1000||cfg.steps<11||cfg.steps>200||!std::isfinite(cfg.max_worker_ms)||cfg.max_worker_ms<1||cfg.max_worker_ms>10000)throw std::runtime_error("TESO bounded settings invalid");worker_=std::thread([this]{work();});}
Online::~Online(){finish();}
void Online::finish(){cancelled_=true;{std::lock_guard<std::mutex>l(mutex_);stopping_=true;queued_.reset();}cv_.notify_all();if(worker_.joinable())worker_.join();}
bool Online::submit(const FramePair&f,const MotionResult&m){if(f.meta.pair_id%cfg_.sample_stride)return false;Sample s;s.id=f.meta.pair_id;s.ns=f.meta.timestamp_ns;for(int e=0;e<2;++e){if(f.search[e].type()!=CV_8UC1||f.search[e].size()!=cv::Size(640,360))return false;s.image[e]=f.search[e].clone();if(m.valid&&!m.eyes[e].stages[6].empty())s.mask[e]=m.eyes[e].stages[6].clone();}
 {std::lock_guard<std::mutex>l(mutex_);if(stopping_)return false;++submitted_;if(queued_)++replaced_;queued_=std::move(s);}cv_.notify_one();return true;}
void Online::waitIdle(){std::unique_lock<std::mutex>l(mutex_);cv_.wait(l,[&]{return !busy_&&!queued_;});}
std::optional<Proposal> Online::take(){std::lock_guard<std::mutex>l(mutex_);auto p=std::move(ready_);ready_.reset();return p;}
Json Online::statistics()const{std::lock_guard<std::mutex>l(mutex_);std::vector<double> t(times_.begin(),times_.end());std::sort(t.begin(),t.end());return {{"submitted",submitted_},{"replaced",replaced_},{"processed",processed_},{"accepted",accepted_},{"busy",busy_},{"queued",bool(queued_)},{"last",last_},{"reason_counts",reasons_},{"sample_stride",cfg_.sample_stride},{"feature_limit",cfg_.features},{"optimizer_steps",cfg_.steps},{"worker_budget_ms",cfg_.max_worker_ms},{"queue_capacity",1},{"truth_loaded",false},{"worker_mean_ms",processed_?worker_sum_ms_/processed_:0},{"worker_max_ms",worker_max_ms_},{"worker_recent_count",t.size()},{"worker_recent_p95_ms",t.empty()?0:t[size_t(.95*(t.size()-1))]}};}
std::vector<Json> Online::diagnostics(){std::lock_guard<std::mutex>l(mutex_);std::vector<Json> d(diagnostics_.begin(),diagnostics_.end());diagnostics_.clear();return d;}
void Online::work(){
#ifdef __linux__
 if(std::getenv("CHAIN_PIN")){cpu_set_t mask;CPU_ZERO(&mask);CPU_SET(5,&mask);sched_setaffinity(0,sizeof(mask),&mask);}
#endif
 for(;;){Sample s;{std::unique_lock<std::mutex>l(mutex_);cv_.wait(l,[&]{return stopping_||queued_.has_value();});if(stopping_&&!queued_)return;s=std::move(*queued_);queued_.reset();busy_=true;last_={{"accepted",false},{"reason","insufficient_independent_features"}};}auto start=Clock::now();std::optional<Proposal> p;Json status;try{p=optimize(s);if(p)status=p->validation;else{std::lock_guard<std::mutex>l(mutex_);status=last_;}}catch(const std::exception&e){status={{"accepted",false},{"reason","optimizer_error"},{"error",e.what()}};}
 status["source_pair_id"]=s.id;double elapsed=std::chrono::duration<double,std::milli>(Clock::now()-start).count();status["worker_ms"]=elapsed;{std::lock_guard<std::mutex>l(mutex_);++processed_;busy_=false;last_=status;auto reason=status.value("reason",std::string("unspecified"));reasons_[reason]=reasons_.value(reason,uint64_t(0))+1;worker_sum_ms_+=elapsed;worker_max_ms_=std::max(worker_max_ms_,elapsed);times_.push_back(elapsed);if(times_.size()>512)times_.pop_front();diagnostics_.push_back(status);if(diagnostics_.size()>32)diagnostics_.pop_front();if(p){++accepted_;ready_=std::move(p);}}cv_.notify_all();}}
std::optional<Proposal> Online::optimize(const Sample&s){auto began=Clock::now();auto abort=[&]{bool stop=cancelled_.load();bool overdue=std::chrono::duration<double,std::milli>(Clock::now()-began).count()>cfg_.max_worker_ms;if(!stop&&!overdue)return false;std::lock_guard<std::mutex>l(mutex_);last_={{"accepted",false},{"reason",stop?"stopped_after_main_chain":"worker_budget_exceeded"}};return true;};if(abort())return {};auto sift=cv::SIFT::create(cfg_.features);std::array<std::vector<cv::KeyPoint>,2> kp;std::array<cv::Mat,2> des;std::array<std::vector<cv::Point2d>,2> raw,und;
 for(int e=0;e<2;++e){cv::Mat mask(s.image[e].size(),CV_8U,cv::Scalar(255));if(!s.mask[e].empty()){cv::Mat moving;cv::dilate(s.mask[e],moving,cv::getStructuringElement(cv::MORPH_RECT,{11,11}));cv::compare(moving,0,mask,cv::CMP_EQ);}sift->detectAndCompute(s.image[e],mask,kp[e],des[e]);if(abort())return {};if(des[e].rows<30)return {};for(auto &k:kp[e])raw[e].emplace_back(2*k.pt.x+.5,2*k.pt.y+.5);und[e]=undistort(raw[e],seed_,e,true);}
 cv::BFMatcher matcher(cv::NORM_L2);std::vector<std::vector<cv::DMatch>> fw,rv;matcher.knnMatch(des[0],des[1],fw,2);matcher.knnMatch(des[1],des[0],rv,2);
 std::vector<std::pair<cv::Point2d,cv::Point2d>> held;std::set<int> excluded[2],cells;
 for(size_t i=0;i<fw.size();++i){if(fw[i].size()<2||fw[i][0].distance>=.75f*fw[i][1].distance)continue;int j=fw[i][0].trainIdx;if(rv[j].size()<2||rv[j][0].trainIdx!=int(i)||rv[j][0].distance>=.75f*rv[j][1].distance)continue;
  // Split by spatial location, before fitting. Every held endpoint is excluded
  // from BOTH directions of the optimizer, not merely from its final score.
  if((int(raw[0][i].x/80)+int(raw[0][i].y/60))%3!=0)continue;
  held.emplace_back(und[0][i],und[1][j]);excluded[0].insert(int(i));excluded[1].insert(j);cells.insert(int(raw[0][i].x/320)+4*int(raw[0][i].y/240));}
 if(abort())return {};
 if(held.size()<24||cells.size()<6)return {};
 validation_.push_back(held);while(validation_.size()>4)validation_.pop_front();
 std::array<cv::Mat,2> train;std::array<std::vector<cv::Vec3d>,2> norm;
 for(int e=0;e<2;++e)for(int i=0;i<des[e].rows;++i)if(!excluded[e].count(i)){train[e].push_back(des[e].row(i));norm[e].push_back(normal(und[e][i],m3(seed_[e?"K_right":"K_left"])));}
 if(train[0].rows<5||train[1].rows<5)return {};
 std::vector<Neighbors> sets[2];for(int e=0;e<2;++e){std::vector<std::vector<cv::DMatch>> matches;matcher.knnMatch(train[e],train[1-e],matches,5);for(size_t i=0;i<matches.size();++i){Neighbors n;n.x=norm[e][i];for(auto &match:matches[i])n.ys.push_back(norm[1-e][match.trainIdx]);sets[e].push_back(std::move(n));}}
 Optimizer optimizer(essential(active_),cfg_.sigma);for(int i=0;i<cfg_.steps;++i){if(abort())return {};optimizer.step(sets[0],sets[1]);}auto candidate=calibrationFromEssential(seed_,optimizer.essential());auto old=essential(active_),updated=essential(candidate);
 std::vector<double> before,after;double ba=0,aa=0;for(auto &h:validation_)for(auto &p:h){double a=sampsonPixels(old,p.first,p.second,seed_),b=sampsonPixels(updated,p.first,p.second,seed_);before.push_back(a);after.push_back(b);ba+=a*a;aa+=b*b;}
 double br=std::sqrt(ba/before.size()),ar=std::sqrt(aa/after.size());auto t=candidate["T_m"].get<std::vector<double>>(),st=seed_["T_m"].get<std::vector<double>>();cv::Vec3d tv(t[0],t[1],t[2]),sv(st[0],st[1],st[2]);double angle=std::acos(std::clamp(tv.dot(sv)/(cv::norm(tv)*cv::norm(sv)),-1.,1.))*180/CV_PI;
 bool ok=improves(br,ar,median(before),median(after))&&rotation(m3(candidate["R_left_to_right"])*m3(seed_["R_left_to_right"]).t())<=1.0&&angle<=2.0;
 Json report={{"accepted",ok},{"holdout_pairs",before.size()},{"current_holdout",held.size()},{"coverage_cells",cells.size()},{"before_sampson_rms_px",br},{"after_sampson_rms_px",ar},{"before_median_px",median(before)},{"after_median_px",median(after)},{"translation_direction_change_deg",angle},{"reason",ok?"heldout_improvement":"heldout_or_pose_guard_rejected"}};
 // Keep rejected diagnostics too, without publishing a calibration.
 {std::lock_guard<std::mutex>l(mutex_);last_=report;}
 if(!ok||abort())return {};
 candidate["online_teso"]={{"method","TESO_5DOF_CPP"},{"source_pair_id",s.id},{"source_time_ns",s.ns},{"validation",report},{"intrinsics_fixed",true},{"baseline_length_fixed",true},{"world_pose","preserved_left_camera_frame"}};
 active_=candidate;return Proposal{candidate,report,s.id,s.ns};
}
} // namespace pipeline::teso
