#include "pipeline/pipeline.hpp"
#include <algorithm>
namespace pipeline {
static void validateBoxes(const Json &boxes) {
  if (!boxes.is_array())
    throw std::runtime_error("boxes must be an array");
  for (auto &box : boxes) {
    std::string cls = box.at("class");
    if (cls != "ball" && cls != "hand" && cls != "racket")
      throw std::runtime_error("class must be ball/hand/racket");
    double score = box.at("confidence");
    auto bounds = box.at("bbox").get<std::vector<double>>();
    if (!std::isfinite(score) || score < 0 || score > 1 || bounds.size() != 4)
      throw std::runtime_error("invalid confidence/bbox");
    for (auto n : bounds)
      if (!std::isfinite(n))
        throw std::runtime_error("nonfinite bbox");
    if (bounds[0] < 0 || bounds[1] < 0 || bounds[2] <= 0 || bounds[3] <= 0 ||
        bounds[0] + bounds[2] > EyeWidth || bounds[1] + bounds[3] > EyeHeight)
      throw std::runtime_error(
          "bbox must be original-eye xywh inside 1280x720");
  }
}
SoftwareMotionBackend::SoftwareMotionBackend(bool dma, MotionConfig c,
                                             int timeout, size_t capacity)
    : cpu_(std::move(c)), dma_(dma), timeout_(timeout), capacity_(capacity) {
  if (timeout < 1 || !capacity)
    throw std::runtime_error("invalid motion backend limits");
}
uint64_t SoftwareMotionBackend::submit(const MotionInput &in,
                                       MotionFault fault) {
  if (pending_.size() >= capacity_)
    throw std::runtime_error("motion queue backpressure");
  auto submitted = Clock::now();
  auto input = dma_ ? deserializeMotionInput(serializeMotionInput(in)) : in;
  MotionResult r;
  if (fault.fail) {
    r.meta = in.meta;
    r.valid = false;
    r.error = "injected processing failure; reference retained";
  } else
    r = cpu_.process(input);
  r.task_id = ++id_;
  r.generation = generation_;
  r.backend = mode();
  if (dma_ && r.valid)
    for (auto &eye : r.eyes)
      eye.stages[6] =
          unpackMask(packMask(eye.stages[6]), SearchWidth, SearchHeight);
  auto now = Clock::now();
  pending_.push_back(
      {std::move(r), submitted,
       now + std::chrono::milliseconds(std::max(0, fault.delay_ms))});
  return id_;
}
std::vector<MotionResult> SoftwareMotionBackend::poll() {
  std::vector<MotionResult> results;
  auto now = Clock::now();
  bool timedout = false;
  for (auto &p : pending_)
    if (now >= p.submitted + std::chrono::milliseconds(timeout_) &&
        p.ready > p.submitted + std::chrono::milliseconds(timeout_))
      timedout = true;
  if (timedout) {
    for (auto &p : pending_) {
      p.result.valid = false;
      p.result.error =
          "motion timeout/cancelled generation; references cleared";
      p.result.completion_ns = monotonicNs();
      results.push_back(std::move(p.result));
    }
    pending_.clear();
    cpu_.reset();
    ++generation_;
    return results;
  }
  for (auto it = pending_.begin(); it != pending_.end();) {
    if (now >= it->ready) {
      it->result.completion_ns = monotonicNs();
      results.push_back(std::move(it->result));
      it = pending_.erase(it);
    } else
      ++it;
  }
  return results;
}
void SoftwareMotionBackend::reset() {
  pending_.clear();
  cpu_.reset();
  ++generation_;
}
DetectorContext::DetectorContext() {
  LiveObjects::increment(LiveObjects::contexts, LiveObjects::peak_contexts);
}
DetectorContext::~DetectorContext() { --LiveObjects::contexts; }
ReplayDetector::ReplayDetector(const Path &p, int delay) : delay_(delay) {
  auto j = Json::parse(readText(p));
  if (j.value("schema_version", 0) != 1)
    throw std::runtime_error("replay schema version mismatch");
  records_ = j.at("detections");
  for (auto &r : records_) {
    r.at("source_pair_id").get<uint64_t>();
    auto eye = r.at("eye").get<std::string>();
    if (eye != "left" && eye != "right")
      throw std::runtime_error("replay eye must be left/right");
    validateBoxes(r.at("boxes"));
  }
}
DetectionResult ReplayDetector::infer(const DetectorContext &c,
                                      const std::atomic<bool> &stop,
                                      int timeout) {
  DetectionResult r;
  r.meta = c.meta;
  r.eye = c.eye;
  r.task_id = c.task_id;
  r.generation = c.generation;
  r.backend = mode();
  auto deadline = Clock::now() + std::chrono::milliseconds(timeout),
       ready = Clock::now() + std::chrono::milliseconds(delay_);
  while (Clock::now() < ready && !stop) {
    if (Clock::now() >= deadline) {
      r.status = "expired";
      r.completed_ns = monotonicNs();
      return r;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  if (stop)
    r.status = "cancelled";
  else
    for (auto &j : records_)
      if (j.at("source_pair_id").get<uint64_t>() == c.meta.pair_id &&
          j.at("eye") == eyeName(c.eye)) {
        r.boxes = j.at("boxes");
        r.meta.model_version = j.value("model_version", "replay-v1");
        break;
      }
  r.completed_ns = monotonicNs();
  return r;
}
DetectorScheduler::DetectorScheduler(std::unique_ptr<DetectorBackend> b,
                                     int rate, int timeout,
                                     size_t pendingCapacity,
                                     size_t completionCapacity)
    : backend_(std::move(b)), jobs_(pendingCapacity),
      completed_(completionCapacity), rate_(rate), timeout_(timeout) {
  if (!backend_ || rate < 1 || timeout < 1)
    throw std::runtime_error("invalid detector scheduler");
  worker_ = std::thread(&DetectorScheduler::worker, this);
}
DetectorScheduler::~DetectorScheduler() {
  stop_ = true;
  jobs_.close();
  completed_.close();
  if (worker_.joinable())
    worker_.join();
}
bool DetectorScheduler::submit(const FramePair &f, Eye eye, bool batch,
                               const MotionResult *motion) {
  std::lock_guard<std::mutex> producerLock(producer_);
  auto now = Clock::now();
  auto interval = std::chrono::nanoseconds(1000000000LL / rate_);
  if (last_ != Clock::time_point{} && now - last_ < interval) {
    if (!batch && eye == Eye::Left)
      return false;
    std::this_thread::sleep_until(last_ + interval);
  }
  last_ = Clock::now();
  auto c = std::make_shared<DetectorContext>();
  c->meta = f.meta;
  c->eye = eye;
  c->gray = f.original[static_cast<int>(eye)].clone();
  c->task_id = ++task_;
  c->generation = generation_;
  c->submitted_ns = monotonicNs();
  if (motion)
    for (int e = 0; e < 2; ++e) {
      c->reference_id[e] = motion->eyes[e].reference_id;
      c->reference_timestamp_ns[e] = motion->eyes[e].reference_timestamp_ns;
      c->reference_valid[e] = motion->eyes[e].reference_valid;
    }
  bool replaced = false;
  std::optional<std::shared_ptr<DetectorContext>> dropped;
  bool ok = jobs_.push(c, !batch, &replaced, &dropped);
  if (ok)
    ++submitted_;
  if (replaced) {
    ++replaced_;
    if (onDiscard)
      onDiscard(**dropped);
  }
  return ok;
}
void DetectorScheduler::worker() {
  while (!stop_) {
    auto job = jobs_.pop(std::chrono::milliseconds(10));
    if (!job) {
      if (jobs_.closed())
        break;
      continue;
    }
    auto &c = **job;
    ++active_;
    DetectionResult r;
    try {
      if (monotonicNs() - c.submitted_ns > int64_t(timeout_) * 1000000) {
        r.status = "expired";
      } else
        r = backend_->infer(c, stop_, timeout_);
    } catch (const std::exception &e) {
      r.status = "backend_error: " + std::string(e.what());
    }
    if (r.status == "ok" &&
        (r.meta.pair_id != c.meta.pair_id ||
         r.meta.timestamp_ns != c.meta.timestamp_ns ||
         r.meta.eye_timestamp_ns != c.meta.eye_timestamp_ns ||
         r.meta.config_version != c.meta.config_version || r.eye != c.eye))
      r.status = "invalid_source_metadata";
    // Completion/deadline use the host clock, independent of backend stamps.
    r.completed_ns = monotonicNs();
    r.meta.pair_id = c.meta.pair_id;
    r.meta.timestamp_ns = c.meta.timestamp_ns;
    r.meta.eye_timestamp_ns = c.meta.eye_timestamp_ns;
    r.meta.camera_frame_id = c.meta.camera_frame_id;
    r.meta.config_version = c.meta.config_version;
    r.meta.calibration_version = c.meta.calibration_version;
    r.meta.time_source = c.meta.time_source;
    r.meta.source = c.meta.source;
    r.eye = c.eye;
    r.reference_id = c.reference_id;
    r.reference_valid = c.reference_valid;
    r.reference_timestamp_ns = c.reference_timestamp_ns;
    r.task_id = c.task_id;
    r.generation = c.generation;
    r.backend = backend_->mode();
    if (r.generation != generation_)
      r.status = "cancelled_generation";
    if (r.status == "ok") {
      try {
        validateBoxes(r.boxes);
      } catch (const std::exception &e) {
        r.status = "invalid_boxes: " + std::string(e.what());
      }
    }
    if (r.completed_ns - c.submitted_ns > int64_t(timeout_) * 1000000) {
      r.status = "expired";
      r.boxes = Json::array();
    }
    if (r.status != "ok")
      r.boxes = Json::array();
    if (r.status == "expired")
      ++expired_;
    bool sent = completed_.push(std::move(r));
    --active_;
    if (!sent)
      break;
  }
  done_ = true;
}
std::vector<DetectionResult> DetectorScheduler::poll() {
  std::vector<DetectionResult> out;
  while (auto r = completed_.pop())
    out.push_back(std::move(*r));
  return out;
}
void DetectorScheduler::finish() { jobs_.close(); }
void DetectorScheduler::reset() { ++generation_; }
Json DetectorScheduler::statistics() const {
  return {{"submitted", submitted_.load()},
          {"replaced", replaced_.load()},
          {"expired", expired_.load()},
          {"pending", jobs_.size()},
          {"active", active_.load()},
          {"completed_pending", completed_.size()},
          {"pending_peak", jobs_.peak()},
          {"completion_peak", completed_.peak()},
          {"rate_per_second", rate_},
          {"done", done_.load()}};
}
#ifdef PIPELINE_HAS_B_MODULE
void register_b_module(Registry &);
#endif
#ifdef PIPELINE_HAS_C_MODULE
void register_c_module(Registry &);
#endif
#ifdef PIPELINE_HAS_DMA_MODULE
void register_dma_module(Registry &);
#endif
Registry moduleRegistry() {
  Registry r;
#ifdef PIPELINE_HAS_B_MODULE
  register_b_module(r);
#endif
#ifdef PIPELINE_HAS_C_MODULE
  register_c_module(r);
#endif
#ifdef PIPELINE_HAS_DMA_MODULE
  register_dma_module(r);
#endif
  return r;
}
std::unique_ptr<MotionBackend> unavailablePcieBackend() {
  throw std::runtime_error(
      "PCIe unavailable: supply AFH03 DMA driver/API, endpoint descriptor map, "
      "DDR3L controller project and approved mask protocol; CPU fallback is "
      "not automatic");
}
} // namespace pipeline
