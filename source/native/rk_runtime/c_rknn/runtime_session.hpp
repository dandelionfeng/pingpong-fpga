#pragma once
#include <cstdint>
#include <memory>
#include <map>
#include <string>
#include <vector>

namespace c_actual {
struct RknnSharedContext;
void resetRuntimeTimings();
void recordDiagnosticTiming(const std::string&, double);
std::map<std::string,double> lastRuntimeTimings();
// Retains the existing internal call surface while replacing graph execution
// with RKNN. All original preprocessing, temporal logic and decoding are reused.
class OrtSession {
public:
  bool load(const std::string &path, bool use_cuda, int intra_op_threads, std::string *error);
  bool ok() const { return static_cast<bool>(session_); }
  void release() { session_.reset(); }
  std::vector<int64_t> inputShape() const;
  std::vector<int64_t> outputShape() const;
  const std::string &inputName() const { return input_name_; }
  const std::string &outputName() const { return output_name_; }
  bool run(const std::vector<float> &input, const std::vector<int64_t> &input_shape,
           std::vector<float> *output, std::vector<int64_t> *output_shape, std::string *error);
  bool runImage(const uint8_t *bgr, size_t bytes, const std::vector<int64_t>& shape,
                std::vector<float>* output, std::vector<int64_t>* output_shape, std::string* error);
private:
  bool runImpl(const std::vector<float>& input, const std::vector<int64_t>& shape,
               const uint8_t* image, size_t image_bytes,
               std::vector<float>* output, std::vector<int64_t>* output_shape, std::string* error);
  std::shared_ptr<RknnSharedContext> session_;
  std::string input_name_, output_name_;
};
}
