#include "pipeline/pipeline.hpp"
namespace pipeline {
class IntegrationDetector final : public DetectorBackend {
public:
  DetectionResult infer(const DetectorContext &c, const std::atomic<bool> &stop,
                        int timeout) override {
    auto begin = Clock::now();
    while (!stop && Clock::now() - begin < std::chrono::milliseconds(20)) {
      if (Clock::now() - begin > std::chrono::milliseconds(timeout))
        break;
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    if (c.gray.empty() || c.gray.size() != cv::Size(EyeWidth, EyeHeight))
      throw std::runtime_error("C context not owned original eye");
    DetectionResult r;
    r.meta = c.meta;
    r.eye = c.eye;
    r.meta.model_version = "integration-test-no-model";
    r.status = stop ? "cancelled" : "ok";
    r.boxes = Json::array(
        {{{"class", "ball"}, {"confidence", 0.1}, {"bbox", {20, 30, 12, 12}}}});
    return r;
  }
  std::string mode() const override { return "integration-test-detector-v1"; }
};
void register_c_module(Registry &registry) {
  registry.detector = [] { return std::make_unique<IntegrationDetector>(); };
}
} // namespace pipeline
