#include "pipeline/pipeline.hpp"
namespace pipeline {
PcieMotionBackend::PcieMotionBackend(std::unique_ptr<DmaTransport> t,
                                     DmaBinding b, MotionConfig c, int timeout,
                                     size_t capacity)
    : transport_(std::move(t)), binding_(std::move(b)), config_(std::move(c)),
      timeout_(timeout), capacity_(capacity) {
  if (!transport_ || !binding_.encode || !binding_.decode ||
      binding_.approved_protocol.empty())
    throw std::runtime_error("PCIe requires a vendor transport and explicitly "
                             "approved encoder/decoder binding");
  if (timeout < 1 || !capacity)
    throw std::runtime_error("invalid PCIe queue/timeout");
  transport_->reset(generation_);
}
uint64_t PcieMotionBackend::submit(const MotionInput &input,
                                   MotionFault fault) {
  if (fault.delay_ms || fault.fail)
    throw std::runtime_error(
        "software fault injection is not supported in device mode");
  if (pending_.size() >= capacity_)
    throw std::runtime_error("PCIe submission backpressure");
  if (input.meta.config_version != config_.version)
    throw std::runtime_error("PCIe configuration version mismatch");
  for (auto &eye : input.search)
    if (eye.type() != CV_8U ||
        eye.size() != cv::Size(SearchWidth, SearchHeight))
      throw std::runtime_error("PCIe expects two 640x360 search images");
  auto id = ++next_;
  auto bytes = binding_.encode(input, id, generation_);
  // Transport owns/copies descriptor and payload before returning.
  transport_->submit(id, bytes);
  pending_.emplace(
      id,
      Pending{input.meta, Clock::now() + std::chrono::milliseconds(timeout_)});
  return id;
}
std::vector<MotionResult> PcieMotionBackend::poll() {
  std::vector<MotionResult> results;
  auto invalidate = [&](const std::string &error) {
    for (auto &p : pending_) {
      MotionResult r;
      r.meta = p.second.meta;
      r.task_id = p.first;
      r.generation = generation_;
      r.valid = false;
      r.error = error;
      r.backend = mode();
      r.completion_ns = monotonicNs();
      results.push_back(std::move(r));
    }
    reset();
  };
  for (auto &p : pending_)
    if (Clock::now() >= p.second.deadline) {
      invalidate("PCIe completion timeout; firmware references reset");
      return results;
    }
  try {
    // Bounded drain prevents a bad transport from monopolizing the caller.
    for (size_t i = 0; i < capacity_; ++i) {
      auto bytes = transport_->receive(0);
      if (!bytes)
        break;
      auto r = binding_.decode(*bytes);
      if (r.generation != generation_)
        continue;
      auto found = pending_.find(r.task_id);
      if (found == pending_.end())
        throw std::runtime_error("unknown/duplicate DMA completion");
      const auto &m = found->second.meta;
      if (r.meta.pair_id != m.pair_id ||
          r.meta.eye_timestamp_ns != m.eye_timestamp_ns ||
          r.meta.timestamp_ns != m.timestamp_ns ||
          r.meta.config_version != m.config_version)
        throw std::runtime_error("DMA completion source metadata mismatch");
      if (r.valid)
        for (auto &eye : r.eyes) {
          if (eye.stages[6].size() != cv::Size(SearchWidth, SearchHeight))
            throw std::runtime_error("DMA mask geometry mismatch");
          packMask(eye.stages[6]);
        }
      r.meta = m;
      r.backend = mode();
      r.completion_ns = monotonicNs();
      results.push_back(std::move(r));
      pending_.erase(found);
    }
  } catch (const std::exception &e) {
    invalidate("PCIe protocol failure: " + std::string(e.what()));
  }
  return results;
}
void PcieMotionBackend::reset() {
  for (auto &p : pending_)
    transport_->cancel(p.first);
  pending_.clear();
  transport_->reset(++generation_);
}
} // namespace pipeline
