#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <nlohmann/json.hpp>
#include <opencv2/core.hpp>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace pipeline {
using Json = nlohmann::json;
using Path = std::filesystem::path;
using Clock = std::chrono::steady_clock;
constexpr int EyeWidth = 1280, EyeHeight = 720, SearchWidth = 640,
              SearchHeight = 360;
enum class Eye { Left = 0, Right = 1 };
std::string eyeName(Eye eye);
Path utf8Path(const std::string &value);
std::string pathUtf8(const Path &value);
std::string readText(const Path &path);
void writeText(const Path &path, const std::string &value);
std::vector<uint8_t> readBytes(const Path &path);
void writeBytes(const Path &path, const std::vector<uint8_t> &bytes);
void writeImage(const Path &path, const cv::Mat &image);
std::string sha256(const std::vector<uint8_t> &bytes);
std::string fileSha256(const Path &path);
int64_t monotonicNs();
struct Meta {
  uint64_t pair_id = 0;
  int64_t timestamp_ns = 0;
  std::array<int64_t, 2> eye_timestamp_ns{};
  std::array<uint64_t, 2> camera_frame_id{};
  std::string config_version = "a-int-v1", calibration_version = "unavailable",
              model_version = "unavailable", time_source = "unknown",
              source = "file";
};
Json metaJson(const Meta &meta);
Meta parseMeta(const Json &object);
struct LiveObjects {
  inline static std::atomic<int> frames{0}, contexts{0}, peak_frames{0},
      peak_contexts{0};
  static void increment(std::atomic<int> &live, std::atomic<int> &peak);
};
// Immutable, causal BallTrack context, captured BEFORE input/AI queue drops.
// Pixels use the existing C linear 512x288 transform; originals are untouched.
struct DetectorHistoryWindow {
  std::array<cv::Mat, 2> background;
  std::vector<Meta> previous_meta;
  std::array<std::vector<cv::Mat>, 2> previous;
};
struct FramePair {
  Meta meta;
  std::array<cv::Mat, 2> original, search;
  std::shared_ptr<const DetectorHistoryWindow> detector_history;
  FramePair();
  ~FramePair();
  FramePair(const FramePair &) = delete;
  FramePair &operator=(const FramePair &) = delete;
};
using FramePtr = std::shared_ptr<const FramePair>;
class DetectorHistoryBuffer {
public:
  FramePtr attach(FramePtr frame);
  void clear() { previous_.clear(); background_ = {}; last_.reset(); }
private:
  struct Item { Meta meta; std::array<cv::Mat, 2> gray; };
  std::deque<Item> previous_;
  std::array<cv::Mat, 2> background_;
  std::optional<Meta> last_;
};
struct FrameRead {
  FramePtr frame;
  Meta meta;
  std::string error;
  Json evidence = Json::object();
  bool end = false;
  size_t index = 0;
};
class FrameSource {
public:
  virtual ~FrameSource() = default;
  virtual FrameRead next() = 0;
  virtual std::string mode() const = 0;
};
class FileFrameSource final : public FrameSource {
public:
  explicit FileFrameSource(Path manifest, bool verifyHashes = true);
  FrameRead next() override;
  std::string mode() const override { return "file"; }
  size_t size() const { return entries_.size(); }
  void seek(size_t index);
  const Json &manifest() const { return manifest_; }

private:
  Path root_;
  Json manifest_;
  std::vector<Json> entries_;
  std::vector<std::string> validation_;
  size_t index_ = 0;
  bool verify_;
};
Json importExportPackage(const Path &folder, const Path &output);
cv::Mat extractY(const std::vector<uint8_t> &bytes, int width, int height,
                 size_t stride);
// One complete 2560x720 JPEG capture buffer, decoded directly to GRAY8.
cv::Mat decodeMjpeg(const std::vector<uint8_t> &bytes);
cv::Mat average2x2(const cv::Mat &original);
struct Roi {
  cv::Mat image;
  cv::Point origin;
  cv::Rect valid;
  uint64_t pair_id = 0;
  Eye eye = Eye::Left;
  int padding_value = 0;
};
Roi cropRoi(const FramePair &frame, Eye eye, cv::Point2d center, int size = 256,
            int padding = 0);
cv::Point2d searchToOriginal(cv::Point2d point);
cv::Rect searchBoxToOriginal(cv::Rect box);
class FrameCache {
public:
  void put(FramePtr frame);
  FramePtr find(uint64_t pair_id) const;
  void clear();
  size_t size() const;

private:
  std::array<FramePtr, 8> slots_{};
  size_t next_ = 0;
};
template <class T> class BoundedQueue {
public:
  explicit BoundedQueue(size_t capacity) : capacity_(capacity) {
    if (!capacity)
      throw std::invalid_argument("zero queue capacity");
  }
  bool push(T value, bool replaceOldest = false, bool *replaced = nullptr,
            std::optional<T> *dropped = nullptr) {
    std::unique_lock<std::mutex> lock(mutex_);
    if (replaced)
      *replaced = false;
    if (!replaceOldest)
      cv_.wait(lock, [&] { return closed_ || queue_.size() < capacity_; });
    if (closed_)
      return false;
    if (queue_.size() == capacity_) {
      if (dropped)
        *dropped = std::move(queue_.front());
      queue_.pop_front();
      if (replaced)
        *replaced = true;
    }
    queue_.push_back(std::move(value));
    peak_ = std::max(peak_, queue_.size());
    cv_.notify_all();
    return true;
  }
  std::optional<T>
  pop(std::chrono::milliseconds wait = std::chrono::milliseconds(0)) {
    std::unique_lock<std::mutex> lock(mutex_);
    if (wait.count())
      cv_.wait_for(lock, wait, [&] { return closed_ || !queue_.empty(); });
    if (queue_.empty())
      return {};
    T value = std::move(queue_.front());
    queue_.pop_front();
    cv_.notify_all();
    return value;
  }
  void close() {
    std::lock_guard<std::mutex> lock(mutex_);
    closed_ = true;
    cv_.notify_all();
  }
  bool closed() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return closed_;
  }
  size_t size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
  }
  size_t peak() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return peak_;
  }
  size_t capacity() const { return capacity_; }

private:
  size_t capacity_, peak_ = 0;
  mutable std::mutex mutex_;
  std::condition_variable cv_;
  std::deque<T> queue_;
  bool closed_ = false;
};
struct MotionConfig {
  int threshold = 12;
  std::string version = "a-int-v1";
};
struct MotionInput {
  Meta meta;
  std::array<cv::Mat, 2> search;
};
struct EyeMotion {
  std::array<cv::Mat, 7> stages;
  bool reference_valid = false;
  uint64_t reference_id = 0;
  int64_t reference_timestamp_ns = 0;
};
struct MotionResult {
  Meta meta;
  std::array<EyeMotion, 2> eyes;
  bool valid = true;
  std::string error, backend = "cpu";
  uint64_t task_id = 0, generation = 0;
  int64_t completion_ns = 0;
};
cv::Mat integerGaussian(const cv::Mat &image);
cv::Mat binaryMorph(const cv::Mat &image, bool dilate);
std::vector<uint8_t> packMask(const cv::Mat &mask);
cv::Mat unpackMask(const std::vector<uint8_t> &bytes, int width, int height);
class CpuMotion {
public:
  explicit CpuMotion(MotionConfig config = {}) : config_(std::move(config)) {}
  MotionResult process(const MotionInput &input);
  MotionResult process(const FramePair &frame) {
    return process(MotionInput{frame.meta, frame.search});
  }
  void reset();
  void configure(MotionConfig config);

private:
  MotionConfig config_;
  std::array<cv::Mat, 2> previous_;
  std::array<Meta, 2> reference_{};
};
std::vector<uint8_t> serializeMotionInput(const MotionInput &input);
MotionInput deserializeMotionInput(const std::vector<uint8_t> &bytes);
struct MotionFault {
  int delay_ms = 0;
  bool fail = false;
};
class MotionBackend {
public:
  virtual ~MotionBackend() = default;
  virtual uint64_t submit(const MotionInput &input, MotionFault fault = {}) = 0;
  virtual std::vector<MotionResult> poll() = 0;
  virtual void reset() = 0;
  virtual size_t pending() const = 0;
  virtual std::string mode() const = 0;
};
class SoftwareMotionBackend final : public MotionBackend {
public:
  SoftwareMotionBackend(bool dma = false, MotionConfig config = {},
                        int timeoutMs = 500, size_t capacity = 8);
  uint64_t submit(const MotionInput &input, MotionFault fault = {}) override;
  std::vector<MotionResult> poll() override;
  void reset() override;
  size_t pending() const override { return pending_.size(); }
  std::string mode() const override { return dma_ ? "mock-dma" : "cpu"; }

private:
  struct Pending {
    MotionResult result;
    Clock::time_point submitted, ready;
  };
  CpuMotion cpu_;
  bool dma_;
  int timeout_;
  size_t capacity_;
  uint64_t id_ = 0, generation_ = 1;
  std::deque<Pending> pending_;
};
struct DetectorContext {
  Meta meta;
  Eye eye = Eye::Left;
  cv::Mat gray;
  std::shared_ptr<const DetectorHistoryWindow> detector_history;
  cv::Point origin{};
  cv::Size original_size{EyeWidth, EyeHeight};
  uint64_t task_id = 0, generation = 0;
  int64_t submitted_ns = 0;
  std::array<uint64_t, 2> reference_id{};
  std::array<int64_t, 2> reference_timestamp_ns{};
  std::array<bool, 2> reference_valid{};
  DetectorContext();
  ~DetectorContext();
  DetectorContext(const DetectorContext &) = delete;
};
struct DetectionResult {
  Meta meta;
  Eye eye = Eye::Left;
  uint64_t task_id = 0, generation = 0;
  int64_t completed_ns = 0;
  std::array<uint64_t, 2> reference_id{};
  std::array<int64_t, 2> reference_timestamp_ns{};
  std::array<bool, 2> reference_valid{};
  std::string status = "ok", backend = "unavailable";
  Json boxes = Json::array();
  // Optional state/provenance; non-observations never become detection boxes.
  Json diagnostics = Json::object();
};
class DetectorBackend {
public:
  virtual ~DetectorBackend() = default;
  // Must honor stop/deadline. Backend implementations own model-specific
  // preprocessing and postprocessing.
  virtual DetectionResult infer(const DetectorContext &context,
                                const std::atomic<bool> &stop,
                                int timeoutMs) = 0;
  virtual std::string mode() const = 0;
};
class ReplayDetector final : public DetectorBackend {
public:
  explicit ReplayDetector(const Path &file, int delayMs = 0);
  DetectionResult infer(const DetectorContext &, const std::atomic<bool> &,
                        int) override;
  std::string mode() const override { return "detection-replay"; }

private:
  Json records_;
  int delay_;
};
class DetectorScheduler {
public:
  DetectorScheduler(std::unique_ptr<DetectorBackend> backend, int rate = 25,
                    int timeoutMs = 500, size_t pendingCapacity = 2,
                    size_t completionCapacity = 8);
  ~DetectorScheduler();
  bool submit(const FramePair &frame, Eye eye, bool batch,
              const MotionResult *motion = nullptr);
  // One queue item owns both eyes; the shared rate still counts eye jobs.
  bool submitStereo(const FramePair &, bool batch,
                    const MotionResult *motion = nullptr);
  std::function<void(const DetectorContext &)> onDiscard;
  std::vector<DetectionResult> poll();
  void finish();
  void reset();
  Json statistics() const;

private:
  void worker();
  bool submitGroup(const FramePair &, const std::vector<Eye> &, bool,
                   const MotionResult *);
  std::unique_ptr<DetectorBackend> backend_;
  BoundedQueue<std::vector<std::shared_ptr<DetectorContext>>> jobs_;
  BoundedQueue<DetectionResult> completed_;
  std::thread worker_;
  std::atomic<bool> stop_{false}, done_{false};
  std::atomic<int> active_{0};
  std::atomic<uint64_t> generation_{1}, submitted_{0}, replaced_{0},
      expired_{0};
  uint64_t task_ = 0;
  std::mutex producer_;
  int rate_, timeout_;
  Clock::time_point last_{};
};
class MeasurementModule {
public:
  virtual ~MeasurementModule() = default;
  // Optional CPU online-stereo update. Default modules retain frozen calibration.
  virtual bool tryOnlineCalibration(const Json&,const std::string&) { return false; }
  virtual void acceptDetections(const std::vector<DetectionResult> &) {};
  virtual void retainDetectionFrame(FramePtr, const MotionResult &) {};
  virtual void discardDetectionFrame(const Meta &) {};
  virtual std::vector<Json> takeUpdates() { return {}; }
  virtual Json process(const FramePair &, const MotionResult &,
                       const std::vector<DetectionResult> &) = 0;
  virtual std::string version() const = 0;
  // B requests right-eye semantics on this source frame when needed.
  virtual bool requestRightDetection(const FramePair &,
                                     const MotionResult &) const {
    return false;
  }
};
struct Registry {
  std::function<std::unique_ptr<MeasurementModule>()> measurement;
  std::function<std::unique_ptr<DetectorBackend>()> detector;
  std::function<std::unique_ptr<MotionBackend>(MotionConfig, int, size_t)>
      motion;
};
Registry moduleRegistry();
// Per-calling-thread model configuration. Factories consume it synchronously.
void setDetectorConfiguration(const Path &path);
Path detectorConfiguration();
// Optional B calibration for this calling thread; factories consume it now.
void setMeasurementCalibration(const Path &path);
Path measurementCalibration();
struct RunConfig {
  std::string motion = "cpu", detector = "none";
  bool full = false, realtime = false, save_images = true, save_stages = true;
  int timeout_ms = 500, detector_rate = 25, mock_delay_ms = 0,
      detector_delay_ms = 0;
  int detector_timeout_ms = 0; // 0 keeps the legacy shared timeout.
  uint64_t repeat = 1;
  size_t input_queue = 8, detection_queue = 2, completion_queue = 8,
         motion_queue = 8;
  bool detect_right = false;
  Path replay;
  Path detector_config;
  Path measurement_calibration;
  MotionConfig algorithm;
  std::shared_ptr<std::atomic<bool>> cancellation;
};
class RunWriter {
public:
  RunWriter(Path output, Json configuration);
  void frame(const FramePair &, const MotionResult &,
             const Json &measurement = Json());
  void detection(const DetectionResult &);
  void measurementUpdate(const Json &);
  void error(const Meta &, const std::string &, const std::string &,
             const Json &evidence = Json::object());
  void finish(Json summary);
  const Path &root() const { return root_; }

private:
  Path root_;
  Json configuration_;
  std::unique_ptr<std::ostream> frames_, detections_, errors_, csv_, updates_;
  std::mutex mutex_;
  uint64_t count_ = 0;
  uint64_t update_count_ = 0;
  bool images_ = true, stages_ = true;
};
Json runPipeline(const Path &manifest, const Path &output,
                 const RunConfig &config,
                 std::function<void(Json)> progress = {});

// Linux ioctl/read boundary supports device-independent fault tests.
class V4l2Syscalls {
public:
  virtual ~V4l2Syscalls() = default;
  virtual int openDevice(const std::string &) = 0;
  virtual int control(int, unsigned long, void *) = 0;
  virtual int wait(int, int) = 0;
  virtual void *map(int, size_t, int64_t) = 0;
  virtual int unmap(void *, size_t) = 0;
  virtual int closeDevice(int) = 0;
};
std::unique_ptr<V4l2Syscalls> nativeV4l2Syscalls();
class V4l2FrameSource final : public FrameSource {
public:
  using PacketObserver = std::function<void(const Meta &, const std::vector<uint8_t> &)>;
  void observeMjpeg(PacketObserver observer) { packet_observer_ = std::move(observer); }
  V4l2FrameSource(std::string device,
                  std::unique_ptr<V4l2Syscalls> calls = nativeV4l2Syscalls(),
                  int exposure = 0, std::string pixelFormat = "auto"); // 0: automatic; >0: manual
  ~V4l2FrameSource();
  const Json &exposureConfiguration() const { return exposure_configuration_; }
  FrameRead next() override;
  std::string mode() const override { return "v4l2"; }

private:
  std::unique_ptr<V4l2Syscalls> calls_;
  int fd_ = -1;
  size_t stride_ = 0;
  uint32_t pixel_format_ = 0;
  Json exposure_configuration_ = Json::object();
  PacketObserver packet_observer_;
  uint64_t pair_ = 0;
  struct Buffer {
    void *data = nullptr;
    size_t size = 0;
  };
  std::vector<Buffer> buffers_;
  void cleanup();
};
class DmaTransport {
public:
  virtual ~DmaTransport() = default;
  virtual void submit(uint64_t, const std::vector<uint8_t> &) = 0;
  virtual std::optional<std::vector<uint8_t>> receive(int timeoutMs) = 0;
  virtual void cancel(uint64_t) = 0;
  // Must cancel outstanding DMA and clear firmware reference state.
  virtual void reset(uint64_t generation) = 0;
};
struct DmaBinding {
  std::string approved_protocol;
  std::function<std::vector<uint8_t>(const MotionInput &, uint64_t, uint64_t)>
      encode;
  std::function<MotionResult(const std::vector<uint8_t> &)> decode;
};
class PcieMotionBackend final : public MotionBackend {
public:
  PcieMotionBackend(std::unique_ptr<DmaTransport>, DmaBinding,
                    MotionConfig = {}, int timeoutMs = 500,
                    size_t capacity = 8);
  uint64_t submit(const MotionInput &, MotionFault = {}) override;
  std::vector<MotionResult> poll() override;
  void reset() override;
  size_t pending() const override { return pending_.size(); }
  std::string mode() const override { return "pcie"; }

private:
  struct Pending {
    Meta meta;
    Clock::time_point deadline;
  };
  std::unique_ptr<DmaTransport> transport_;
  DmaBinding binding_;
  MotionConfig config_;
  int timeout_;
  size_t capacity_;
  uint64_t next_ = 0, generation_ = 1;
  std::map<uint64_t, Pending> pending_;
};
std::unique_ptr<MotionBackend> unavailablePcieBackend();
} // namespace pipeline
