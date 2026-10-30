#pragma once
#include "pipeline/pipeline.hpp"
#include <opencv2/calib3d.hpp>
#include <opencv2/features2d.hpp>
#include <atomic>

// TESO, Moravec/Sara/Sugimoto, arXiv:2604.19420, equations 3--8.
// C++ adaptation of the authors' 5-DOF essential-manifold optimizer:
// https://github.com/moravecj/TESO/tree/a309db1f5e5c15ac38e2cf8036f441787be33327
// Attribution and CC BY-NC 4.0 terms: see NOTICE.md.
namespace pipeline::teso {
using M3=cv::Matx33d;
using V5=cv::Vec<double,5>;
struct Neighbors { cv::Vec3d x; std::vector<cv::Vec3d> ys; };
class Optimizer {
public:
  explicit Optimizer(const M3 &E,double sigma=.00075);
  V5 step(const std::vector<Neighbors>& forward,const std::vector<Neighbors>& reverse);
  M3 essential() const;
  M3 derivative(int i) const;
  std::pair<V5,V5> derivatives(const std::vector<Neighbors>&,const std::vector<Neighbors>&) const;
  static M3 omega1(const V5&),omega2(const V5&);
private:
  M3 U_,Vt_;
  V5 memory_=V5::all(1),gradient_=V5::all(0),variance_=V5::all(0),hessian_=V5::all(0);
  int burn_=10;
  double sigma_;
};
struct Settings {
  int sample_stride=30,features=350,steps=32;
  double sigma=.00075;
  double max_worker_ms=1000;
};
struct Proposal { Json calibration,validation; uint64_t source_pair_id=0; int64_t source_time_ns=0; };
class Online {
public:
  Online(Json seed,Settings settings={});
  ~Online();
  // Only copies the two 640x360 searches and their FPGA masks at sparse cadence.
  // No descriptor extraction, optimizer, rectification or file I/O on this path.
  bool submit(const FramePair&,const MotionResult&);
  std::optional<Proposal> take();
  Json statistics() const;
  std::vector<Json> diagnostics();
  void finish();
  void waitIdle(); // offline evaluation only; never called by the live pipeline
private:
  struct Sample { uint64_t id;int64_t ns;std::array<cv::Mat,2> image,mask; };
  void work();
  std::optional<Proposal> optimize(const Sample&);
  Json seed_,active_;
  Settings cfg_;
  mutable std::mutex mutex_;
  std::condition_variable cv_;
  std::optional<Sample> queued_;
  std::optional<Proposal> ready_;
  std::thread worker_;
  bool stopping_=false,busy_=false;
  std::atomic<bool> cancelled_{false};
  uint64_t submitted_=0,replaced_=0,processed_=0,accepted_=0;
  Json last_=Json::object();
  Json reasons_=Json::object();
  std::deque<Json> diagnostics_;
  std::deque<double> times_;
  double worker_sum_ms_=0,worker_max_ms_=0;
  std::deque<std::vector<std::pair<cv::Point2d,cv::Point2d>>> validation_;
};
M3 essential(const Json&);
Json calibrationFromEssential(const Json &seed,const M3 &E);
double sampsonPixels(const M3&,cv::Point2d,cv::Point2d,const Json&);
bool improves(double oldRms,double newRms,double oldMedian,double newMedian);
} // namespace pipeline::teso
