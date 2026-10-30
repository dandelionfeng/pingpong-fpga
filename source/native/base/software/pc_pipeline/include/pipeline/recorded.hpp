#pragma once
#include "pipeline/pipeline.hpp"
namespace pipeline {
// Immutable actual-model record replay; never invokes a neural network.
class RecordedDetections {
public:
  RecordedDetections(const Path &manifest, const Path &jsonl);
  std::vector<DetectionResult> frame(const FramePair &, const MotionResult &) const;
  const Json &provenance() const { return provenance_; }
private:
  std::map<uint64_t, std::array<DetectionResult, 2>> records_;
  Json provenance_;
};
} // namespace pipeline
