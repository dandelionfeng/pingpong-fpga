#include "pipeline/pipeline.hpp"
namespace pipeline {
class IntegrationMeasurement final : public MeasurementModule {
public:
  void acceptDetections(const std::vector<DetectionResult> &results) override {
    for (auto &r : results)
      if (r.status == "ok")
        received_.insert(r.meta.pair_id);
  }
  Json process(const FramePair &f, const MotionResult &m,
               const std::vector<DetectionResult> &results) override {
    if (m.meta.pair_id != f.meta.pair_id)
      throw std::runtime_error("test B source mismatch");
    for (auto &r : results)
      if (r.meta.pair_id != f.meta.pair_id)
        throw std::runtime_error("test B cross-frame detection");
    return {{"pair_id", f.meta.pair_id},
            {"timestamp_ns", f.meta.timestamp_ns},
            {"status", "invalid_integration_test"},
            {"version", version()},
            {"units", "metres"},
            {"observations", Json::array()},
            {"detections_received_so_far", received_.size()}};
  }
  bool requestRightDetection(const FramePair &,
                             const MotionResult &) const override {
    return true;
  }
  std::string version() const override {
    return "integration-test-measurement-v1";
  }

private:
  std::set<uint64_t> received_;
};
void register_b_module(Registry &registry) {
  registry.measurement = [] {
    return std::make_unique<IntegrationMeasurement>();
  };
}
} // namespace pipeline
