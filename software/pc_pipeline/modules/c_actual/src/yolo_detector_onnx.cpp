#include "internal_onnx.hpp"

#include <algorithm>
#include <array>
#include <numeric>
#include <stdexcept>

#ifdef _WIN32
// For MultiByteToWideChar / CP_UTF8 (UTF-8 path decoding on Windows).
// NOMINMAX keeps windows.h from defining min/max macros.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

#include <opencv2/imgproc.hpp>

namespace c_actual {

// ------------------------------------------------------------------ session
#ifdef _WIN32
// The engine receives UTF-8 paths. ONNX Runtime's Windows entry point takes a
// wide string, so decode properly (a naive std::wstring(path.begin(), end())
// would mangle every non-ASCII character, e.g. Chinese directory names).
std::wstring utf8ToWide(const std::string &text) {
  if (text.empty()) return std::wstring();
  const int size = MultiByteToWideChar(CP_UTF8, 0, text.c_str(),
                                       static_cast<int>(text.size()), nullptr, 0);
  if (size <= 0) return std::wstring(text.begin(), text.end());
  std::wstring wide(static_cast<size_t>(size), L'\0');
  MultiByteToWideChar(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()),
                      wide.data(), size);
  return wide;
}
#endif

bool OrtSession::load(const std::string &path, bool use_cuda, int intra_op_threads,
                      std::string *error) {
  try {
    options_ = Ort::SessionOptions();
    options_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    if (intra_op_threads > 0) {
      options_.SetIntraOpNumThreads(intra_op_threads);
    }
    if (use_cuda) {
      // CUDA is optional: if the provider is absent we fall back to CPU rather
      // than failing, so the captain never needs a CUDA install to run the demo.
      try {
        OrtCUDAProviderOptions cuda_options{};
        cuda_options.device_id = 0;
        options_.AppendExecutionProvider_CUDA(cuda_options);
      } catch (const Ort::Exception &) {
        // ignore: CPU provider remains available
      } catch (const std::exception &) {
        // ignore
      }
    }
#ifdef _WIN32
    const std::wstring wide = utf8ToWide(path);
    session_ = std::make_unique<Ort::Session>(env_, wide.c_str(), options_);
#else
    session_ = std::make_unique<Ort::Session>(env_, path.c_str(), options_);
#endif
    Ort::AllocatorWithDefaultOptions allocator;
    input_names_.clear();
    output_names_.clear();
    for (size_t i = 0; i < session_->GetInputCount(); ++i) {
      input_names_.emplace_back(session_->GetInputNameAllocated(i, allocator).get());
    }
    for (size_t i = 0; i < session_->GetOutputCount(); ++i) {
      output_names_.emplace_back(session_->GetOutputNameAllocated(i, allocator).get());
    }
    if (input_names_.empty() || output_names_.empty()) {
      if (error) *error = "model has no inputs or no outputs: " + path;
      session_.reset();
      return false;
    }
    input_name_ = input_names_.front();
    output_name_ = output_names_.front();
    return true;
  } catch (const Ort::Exception &exc) {
    if (error) *error = std::string("ONNX Runtime: ") + exc.what();
    session_.reset();
    return false;
  } catch (const std::exception &exc) {
    if (error) *error = std::string("load failed: ") + exc.what();
    session_.reset();
    return false;
  }
}

std::vector<int64_t> OrtSession::inputShape() const {
  if (!session_) return {};
  return session_->GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
}

std::vector<int64_t> OrtSession::outputShape() const {
  if (!session_) return {};
  return session_->GetOutputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
}

bool OrtSession::run(const std::vector<float> &input, const std::vector<int64_t> &input_shape,
                     std::vector<float> *output, std::vector<int64_t> *output_shape,
                     std::string *error) {
  if (!session_) {
    if (error) *error = "session not loaded";
    return false;
  }
  try {
    auto memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory_info, const_cast<float *>(input.data()), input.size(),
        input_shape.data(), input_shape.size());

    const char *input_names[] = {input_name_.c_str()};
    const char *output_names[] = {output_name_.c_str()};
    auto outputs = session_->Run(Ort::RunOptions{nullptr}, input_names, &input_tensor, 1,
                                 output_names, 1);

    auto &tensor = outputs.front();
    auto info = tensor.GetTensorTypeAndShapeInfo();
    *output_shape = info.GetShape();
    const float *data = tensor.GetTensorData<float>();
    const size_t count = info.GetElementCount();
    output->assign(data, data + count);
    return true;
  } catch (const Ort::Exception &exc) {
    if (error) *error = std::string("inference: ") + exc.what();
    return false;
  } catch (const std::exception &exc) {
    if (error) *error = std::string("inference: ") + exc.what();
    return false;
  }
}

// ------------------------------------------------------------------ helpers
std::vector<float> imageToNchw(const cv::Mat &bgr, int size) {
  cv::Mat rgb;
  cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
  cv::Mat resized;
  if (rgb.cols != size || rgb.rows != size) {
    cv::resize(rgb, resized, cv::Size(size, size), 0, 0, cv::INTER_LINEAR);
  } else {
    resized = rgb;
  }
  resized.convertTo(resized, CV_32FC3, 1.0 / 255.0);

  std::vector<float> tensor(static_cast<size_t>(3) * size * size);
  const int plane = size * size;
  for (int y = 0; y < size; ++y) {
    const cv::Vec3f *row = resized.ptr<cv::Vec3f>(y);
    for (int x = 0; x < size; ++x) {
      const cv::Vec3f &px = row[x];
      tensor[0 * plane + y * size + x] = px[0];
      tensor[1 * plane + y * size + x] = px[1];
      tensor[2 * plane + y * size + x] = px[2];
    }
  }
  return tensor;
}

// ------------------------------------------------------------- YOLO detector
bool YoloDetector::load(const std::string &path, const std::vector<std::string> &class_names,
                        const Config &config, bool use_cuda, std::string *error) {
  config_ = config;
  class_names_ = class_names;
  return session_.load(path, use_cuda, config.intra_op_threads, error);
}

std::vector<Box> YoloDetector::detect(const cv::Mat &gray3, float conf_threshold, int out_w,
                                      int out_h) {
  std::vector<Box> result;
  if (!session_.ok() || gray3.empty()) return result;

  float scale = 1.f;
  int pad_x = 0, pad_y = 0;
  cv::Mat letterboxed = preprocess::letterbox(gray3, config_.imgsz, &scale, &pad_x, &pad_y);
  std::vector<float> input = imageToNchw(letterboxed, config_.imgsz);

  std::vector<float> output;
  std::vector<int64_t> shape;
  std::string error;
  // `run` is non-const (it owns the Ort::Env used to create tensors).
  if (!session_.run(input, {1, 3, config_.imgsz, config_.imgsz}, &output, &shape, &error)) {
    return result;
  }
  // Expected: (1, 4 + num_classes, num_anchors)
  if (shape.size() != 3 || shape[0] != 1) return result;
  const int channels = static_cast<int>(shape[1]);
  const int anchors = static_cast<int>(shape[2]);
  const int num_classes = channels - 4;
  if (num_classes <= 0) return result;

  std::vector<Box> candidates;
  for (int a = 0; a < anchors; ++a) {
    float best = 0.f;
    int best_class = -1;
    for (int c = 0; c < num_classes; ++c) {
      const float score = output[static_cast<size_t>(4 + c) * anchors + a];
      if (score > best) {
        best = score;
        best_class = c;
      }
    }
    if (best_class < 0 || best < conf_threshold) continue;
    const float cx = output[static_cast<size_t>(0) * anchors + a];
    const float cy = output[static_cast<size_t>(1) * anchors + a];
    const float w = output[static_cast<size_t>(2) * anchors + a];
    const float h = output[static_cast<size_t>(3) * anchors + a];
    Box box = postprocess::unletterbox(cx, cy, w, h, best, best_class, scale, pad_x, pad_y,
                                       out_w, out_h);
    if (box.w <= 0.f || box.h <= 0.f) continue;
    box.class_name = (best_class < static_cast<int>(class_names_.size()))
                         ? class_names_[best_class]
                         : std::to_string(best_class);
    candidates.push_back(box);
  }
  return postprocess::nms(std::move(candidates), config_.iou, config_.max_det);
}

}  // namespace c_actual
