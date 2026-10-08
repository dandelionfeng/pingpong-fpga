#include "pipeline/pipeline.hpp"
#include <fstream>
#include <iostream>
#include <random>
#ifdef __linux__
#include <linux/videodev2.h>
#include <sys/mman.h>
#endif
using namespace pipeline;
#define CHECK(condition)                                                       \
  do {                                                                         \
    if (!(condition))                                                          \
      throw std::runtime_error(std::string("failed: ") + #condition);          \
  } while (0)
template <class F> void rejects(F fn) {
  bool rejected = false;
  try {
    fn();
  } catch (const std::exception &) {
    rejected = true;
  }
  CHECK(rejected);
}
static std::shared_ptr<FramePair> frame(uint64_t id, int left = 10,
                                        int right = 100) {
  auto f = std::make_shared<FramePair>();
  f->meta.pair_id = id;
  f->meta.timestamp_ns = static_cast<int64_t>(id) * 16000000;
  f->meta.eye_timestamp_ns = {f->meta.timestamp_ns, f->meta.timestamp_ns};
  for (int e = 0; e < 2; ++e) {
    f->original[e] =
        cv::Mat(EyeHeight, EyeWidth, CV_8U, cv::Scalar(e ? right : left));
    f->search[e] =
        cv::Mat(SearchHeight, SearchWidth, CV_8U, cv::Scalar(e ? right : left));
  }
  return f;
}
static cv::Mat oracleGaussian(const cv::Mat &a) {
  cv::Mat out(a.size(), CV_8U);
  int weights[] = {1, 2, 1};
  for (int y = 0; y < a.rows; ++y)
    for (int x = 0; x < a.cols; ++x) {
      int sum = 0;
      for (int dy = -1; dy <= 1; ++dy)
        for (int dx = -1; dx <= 1; ++dx)
          sum += weights[dy + 1] * weights[dx + 1] *
                 a.at<uint8_t>(std::clamp(y + dy, 0, a.rows - 1),
                               std::clamp(x + dx, 0, a.cols - 1));
      out.at<uint8_t>(y, x) = static_cast<uint8_t>((sum + 8) / 16);
    }
  return out;
}
static cv::Mat oracleMorph(const cv::Mat &a, bool dilate) {
  cv::Mat out(a.size(), CV_8U);
  for (int y = 0; y < a.rows; ++y)
    for (int x = 0; x < a.cols; ++x) {
      bool value = !dilate;
      for (int dy = -1; dy <= 1; ++dy)
        for (int dx = -1; dx <= 1; ++dx) {
          bool p = a.at<uint8_t>(std::clamp(y + dy, 0, a.rows - 1),
                                 std::clamp(x + dx, 0, a.cols - 1)) != 0;
          value = dilate ? (value || p) : (value && p);
        }
      out.at<uint8_t>(y, x) = value ? 255 : 0;
    }
  return out;
}
static bool same(const cv::Mat &a, const cv::Mat &b) {
  return a.size() == b.size() && a.type() == b.type() &&
         cv::countNonZero(a != b) == 0;
}
static void pixels() {
  CHECK(sha256({'a', 'b', 'c'}) ==
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  CHECK(sha256({}) ==
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  std::vector<uint8_t> yuy2 = {16, 128, 235, 128, 99, 88,
                               1,  128, 254, 128, 77, 66};
  auto y = extractY(yuy2, 2, 2, 6);
  CHECK(y.at<uint8_t>(0, 0) == 16 && y.at<uint8_t>(0, 1) == 235 &&
        y.at<uint8_t>(1, 1) == 254);
  CHECK(average2x2(y).at<uint8_t>(0, 0) == 127);
  rejects([&] { extractY(yuy2, 3, 2, 6); });
  rejects([&] { extractY(yuy2, 2, 2, 4); });
  cv::Mat a(7, 11, CV_8U);
  std::mt19937 random(722);
  for (int seed = 0; seed < 12; ++seed) {
    for (auto it = a.begin<uint8_t>(); it != a.end<uint8_t>(); ++it)
      *it = static_cast<uint8_t>(random());
    CHECK(same(integerGaussian(a), oracleGaussian(a)));
    for (auto it = a.begin<uint8_t>(); it != a.end<uint8_t>(); ++it)
      *it = (*it & 1) ? 255 : 0;
    CHECK(same(binaryMorph(a, false), oracleMorph(a, false)));
    CHECK(same(binaryMorph(a, true), oracleMorph(a, true)));
  }
  cv::Mat bits = cv::Mat::zeros(2, 16, CV_8U);
  bits.at<uint8_t>(0, 0) = 255;
  bits.at<uint8_t>(0, 7) = 255;
  bits.at<uint8_t>(0, 9) = 255;
  bits.at<uint8_t>(1, 15) = 255;
  CHECK(packMask(bits) == std::vector<uint8_t>({0x81, 0x02, 0x00, 0x80}));
  CHECK(same(unpackMask({0x81, 0x02, 0x00, 0x80}, 16, 2), bits));
  rejects([&] { unpackMask({0}, 16, 2); });
}
static void reference() {
  CpuMotion cpu;
  auto first = cpu.process(*frame(1));
  CHECK(!first.eyes[0].reference_valid &&
        cv::countNonZero(first.eyes[0].stages[6]) == 0);
  auto second = cpu.process(*frame(2, 23, 111));
  CHECK(second.eyes[0].reference_id == 1 && second.eyes[1].reference_id == 1);
  CHECK(cv::countNonZero(second.eyes[0].stages[2]) ==
        SearchWidth * SearchHeight);
  CHECK(cv::countNonZero(second.eyes[1].stages[2]) == 0);
  auto equal = cpu.process(*frame(3, 35, 123));
  CHECK(cv::countNonZero(equal.eyes[0].stages[2]) == 0);
  auto bad = frame(4);
  bad->search[1] = cv::Mat(1, 1, CV_8U);
  CHECK(!cpu.process(*bad).valid);
  auto gap = cpu.process(*frame(7, 48, 123));
  CHECK(gap.eyes[0].reference_id == 3 && gap.eyes[1].reference_id == 3);
  auto mismatch = frame(8);
  mismatch->meta.config_version = "wrong";
  CHECK(!cpu.process(*mismatch).valid);
  cpu.configure({13, "new-v2"});
  auto fresh = frame(9);
  fresh->meta.config_version = "new-v2";
  CHECK(!cpu.process(*fresh).eyes[0].reference_valid);
  cpu.reset();
  CHECK(!cpu.process(*fresh).eyes[1].reference_valid);
}
static void roiCache() {
  auto f = frame(1);
  auto roi = cropRoi(*f, Eye::Left, {0, 0});
  CHECK(roi.origin == cv::Point(-128, -128) &&
        roi.valid == cv::Rect(128, 128, 128, 128));
  CHECK(roi.image.at<uint8_t>(0, 0) == 0 &&
        roi.image.at<uint8_t>(128, 128) == 10);
  CHECK(searchToOriginal({0, 0}) == cv::Point2d(.5, .5));
  CHECK(searchBoxToOriginal({1, 2, 3, 4}) == cv::Rect(2, 4, 6, 8));
  FrameCache cache;
  cache.put(f);
  for (int i = 2; i <= 10; ++i)
    cache.put(frame(i));
  CHECK(cache.size() == 8 && !cache.find(1));
  CHECK(f->original[0].at<uint8_t>(0, 0) == 10);
  cache.clear();
  CHECK(cache.size() == 0);
}
static void dma() {
  auto f = frame(1);
  auto malformed = metaJson(f->meta);
  malformed["pair_id"] = -1;
  rejects([&] { parseMeta(malformed); });
  malformed = metaJson(f->meta);
  malformed["eye_timestamp_ns"] = {1, 1.5};
  rejects([&] { parseMeta(malformed); });
  MotionInput input{f->meta, f->search};
  auto bytes = serializeMotionInput(input);
  const std::vector<uint8_t> fixed = {0x41, 0x4d, 0x30, 0x31, 0x01,
                                      0x00, 0x80, 0x02, 0x68, 0x01};
  CHECK(std::equal(fixed.begin(), fixed.end(), bytes.begin()));
  CHECK(bytes[12] == 0 && bytes[13] == 8 && bytes[14] == 7 && bytes[15] == 0);
  CHECK(size_t(bytes[10] + 256 * bytes[11]) + 16 + 460800 == bytes.size());
  auto decoded = deserializeMotionInput(bytes);
  CHECK(decoded.meta.pair_id == 1 && same(decoded.search[1], input.search[1]));
  bytes[0] = 0;
  rejects([&] { deserializeMotionInput(bytes); });
  SoftwareMotionBackend backend(true, {}, 500, 8);
  backend.submit(input, {160, false});
  auto f2 = frame(2, 23, 111);
  backend.submit({f2->meta, f2->search}, {20, false});
  std::this_thread::sleep_for(std::chrono::milliseconds(30));
  auto early = backend.poll();
  CHECK(early.size() == 1 && early[0].meta.pair_id == 2 &&
        early[0].eyes[0].reference_id == 1);
  std::this_thread::sleep_for(std::chrono::milliseconds(150));
  auto late = backend.poll();
  CHECK(late.size() == 1 && late[0].meta.pair_id == 1);
  auto f3 = frame(3);
  backend.submit({f3->meta, f3->search}, {0, true});
  CHECK(!backend.poll()[0].valid);
  auto f4 = frame(4);
  backend.submit({f4->meta, f4->search});
  CHECK(backend.poll()[0].eyes[0].reference_id == 2);
  SoftwareMotionBackend timeout(true, {}, 20);
  timeout.submit(input, {80, false});
  std::this_thread::sleep_for(std::chrono::milliseconds(25));
  CHECK(!timeout.poll()[0].valid);
  timeout.submit({f2->meta, f2->search});
  CHECK(!timeout.poll()[0].eyes[0].reference_valid);
  rejects([] { unavailablePcieBackend(); });
}
struct FakeDmaState {
  std::deque<uint64_t> ready;
  std::map<uint64_t, MotionResult> decoded;
  uint64_t resets = 0, cancels = 0;
  bool deliver = true, corrupt = false;
};
class FakeDmaTransport final : public DmaTransport {
public:
  explicit FakeDmaTransport(std::shared_ptr<FakeDmaState> state)
      : state_(std::move(state)) {}
  void submit(uint64_t id, const std::vector<uint8_t> &payload) override {
    CHECK(!payload.empty());
    state_->ready.push_back(id);
  }
  std::optional<std::vector<uint8_t>> receive(int) override {
    if (!state_->deliver || state_->ready.empty())
      return {};
    auto id = state_->ready.back();
    state_->ready.pop_back();
    auto text = Json{{"task", id}}.dump();
    return std::vector<uint8_t>(text.begin(), text.end());
  }
  void cancel(uint64_t) override { ++state_->cancels; }
  void reset(uint64_t) override {
    ++state_->resets;
    state_->ready.clear();
  }

private:
  std::shared_ptr<FakeDmaState> state_;
};
static void pcieBoundary() {
  auto state = std::make_shared<FakeDmaState>();
  DmaBinding binding;
  binding.approved_protocol = "integration-test-only-no-vendor";
  binding.encode = [state](const MotionInput &input, uint64_t task,
                           uint64_t generation) {
    MotionResult r;
    r.meta = input.meta;
    r.task_id = task;
    r.generation = generation;
    for (auto &e : r.eyes)
      e.stages[6] = cv::Mat::zeros(SearchHeight, SearchWidth, CV_8U);
    state->decoded[task] = std::move(r);
    return serializeMotionInput(input);
  };
  binding.decode = [state](const std::vector<uint8_t> &bytes) {
    auto id = Json::parse(bytes).at("task").get<uint64_t>();
    auto r = state->decoded.at(id);
    state->decoded.erase(id);
    if (state->corrupt)
      ++r.meta.pair_id;
    return r;
  };
  PcieMotionBackend backend(std::make_unique<FakeDmaTransport>(state), binding,
                            {}, 20, 2);
  auto a = frame(1), b = frame(2);
  backend.submit({a->meta, a->search});
  backend.submit({b->meta, b->search});
  rejects([&] { backend.submit({b->meta, b->search}); });
  auto result = backend.poll();
  CHECK(result.size() == 2 && result[0].meta.pair_id == 2 &&
        result[1].meta.pair_id == 1);
  state->corrupt = true;
  backend.submit({a->meta, a->search});
  result = backend.poll();
  CHECK(result.size() == 1 && !result[0].valid && state->cancels == 1);
  state->corrupt = false;
  state->deliver = false;
  backend.submit({a->meta, a->search});
  std::this_thread::sleep_for(std::chrono::milliseconds(25));
  result = backend.poll();
  CHECK(result.size() == 1 && !result[0].valid && backend.pending() == 0 &&
        state->resets == 3);
}
static Path scratch() {
  auto root = std::filesystem::temp_directory_path() /
              utf8Path("A测试 中文-" + std::to_string(monotonicNs()));
  std::filesystem::create_directories(root);
  return root;
}
static void files() {
  auto dir = scratch();
  std::vector<uint8_t> raw(static_cast<size_t>(EyeWidth + 7) * EyeHeight, 80);
  writeBytes(dir / utf8Path("左.raw"), raw);
  writeBytes(dir / utf8Path("右.raw"), raw);
  Json frames = Json::array();
  for (int i = 1; i <= 5; ++i) {
    auto m = frame(i)->meta;
    auto j = metaJson(m);
    j.update({{"format", "GRAY8"},
              {"width", EyeWidth},
              {"height", EyeHeight},
              {"stride", EyeWidth + 7},
              {"left_file", "左.raw"},
              {"right_file", "右.raw"},
              {"left_sha256", sha256(raw)},
              {"right_sha256", sha256(raw)}});
    frames.push_back(j);
  }
  frames[1]["pair_id"] = 1;
  frames[2]["right_file"] = "missing.raw";
  frames[3]["timestamp_ns"] = 1;
  frames[3]["eye_timestamp_ns"] = {1, 1};
  frames[4]["left_sha256"] = "wrong";
  auto manifest = dir / utf8Path("清单.json");
  writeText(manifest, Json{{"schema_version", 1}, {"frames", frames}}.dump(2));
  FileFrameSource source(manifest);
  auto good = source.next();
  CHECK(good.frame && good.frame->original[1].at<uint8_t>(0, 0) == 80);
  for (int i = 0; i < 4; ++i)
    CHECK(!source.next().error.empty());
  CHECK(source.next().end);
}
class SlowDetector final : public DetectorBackend {
public:
  explicit SlowDetector(int delay) : delay_(delay) {}
  DetectionResult infer(const DetectorContext &c, const std::atomic<bool> &stop,
                        int timeout) override {
    auto begin = Clock::now();
    while (Clock::now() - begin < std::chrono::milliseconds(delay_) && !stop) {
      if (Clock::now() - begin > std::chrono::milliseconds(timeout))
        break;
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    DetectionResult r;
    r.meta = c.meta;
    r.eye = c.eye;
    r.meta.model_version = "test-backend-not-model";
    r.boxes = Json::array(
        {Json{{"class", "ball"}, {"confidence", .7}, {"bbox", {1, 2, 3, 4}}}});
    return r;
  }
  std::string mode() const override { return "test-only-scheduler"; }

private:
  int delay_;
};
static void asynchronous() {
  BoundedQueue<int> q(1);
  CHECK(q.push(1));
  bool replaced = false;
  CHECK(q.push(2, true, &replaced) && replaced);
  CHECK(q.pop() == 2);
  q.close();
  CHECK(!q.push(3));
  for (int delay : {20, 80, 160}) {
    DetectorScheduler scheduler(std::make_unique<SlowDetector>(delay), 1000,
                                500);
    auto f = frame(1);
    scheduler.submit(*f, Eye::Left, true);
    f.reset();
    scheduler.finish();
    std::vector<DetectionResult> results;
    while (!scheduler.statistics()["done"].get<bool>()) {
      auto list = scheduler.poll();
      results.insert(results.end(), list.begin(), list.end());
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    auto last = scheduler.poll();
    results.insert(results.end(), last.begin(), last.end());
    CHECK(results.size() == 1 && results[0].meta.pair_id == 1 &&
          results[0].status == "ok");
    CHECK(scheduler.statistics()["pending_peak"].get<int>() <= 2);
  }
  DetectorScheduler slow(std::make_unique<SlowDetector>(160), 1000, 30);
  for (int i = 1; i <= 20; ++i) {
    slow.submit(*frame(i), i % 2 ? Eye::Left : Eye::Right, false);
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  slow.finish();
  while (!slow.statistics()["done"].get<bool>()) {
    slow.poll();
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  auto list = slow.poll();
  CHECK(slow.statistics()["replaced"].get<int>() > 0);
  CHECK(slow.statistics()["expired"].get<int>() > 0);
}
class ForgedDetector final : public DetectorBackend {
public:
  DetectionResult infer(const DetectorContext &c, const std::atomic<bool> &,
                        int) override {
    DetectionResult r;
    r.meta = c.meta;
    r.eye = c.eye;
    r.meta.pair_id++;
    r.completed_ns = 1;
    r.boxes = Json::array(
        {{{"class", "ball"}, {"confidence", 1.0}, {"bbox", {1, 1, 10, 10}}}});
    return r;
  }
  std::string mode() const override { return "test-forged-source"; }
};
static void forgedSource() {
  DetectorScheduler s(std::make_unique<ForgedDetector>());
  auto f = frame(1);
  s.submit(*f, Eye::Right, true);
  s.finish();
  std::vector<DetectionResult> results;
  while (!s.statistics()["done"].get<bool>()) {
    auto list = s.poll();
    results.insert(results.end(), list.begin(), list.end());
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  auto list = s.poll();
  results.insert(results.end(), list.begin(), list.end());
  CHECK(results.size() == 1 && results[0].status == "invalid_source_metadata" &&
        results[0].boxes.empty());
  CHECK(results[0].meta.pair_id == 1 && results[0].eye == Eye::Right &&
        results[0].completed_ns > 1);
}
#ifdef __linux__
class FakeV4l2 final : public V4l2Syscalls {
public:
  bool timeout = false, short_frame = false;
  std::vector<uint8_t> data =
      std::vector<uint8_t>(EyeWidth * 4 * EyeHeight, 128);
  int close_count = 0;
  int openDevice(const std::string &) override { return 9; }
  int control(int, unsigned long op, void *p) override {
    if (op == VIDIOC_QUERYCAP)
      static_cast<v4l2_capability *>(p)->capabilities =
          V4L2_CAP_STREAMING | V4L2_CAP_VIDEO_CAPTURE;
    if (op == VIDIOC_S_FMT)
      static_cast<v4l2_format *>(p)->fmt.pix.bytesperline = EyeWidth * 4;
    if (op == VIDIOC_REQBUFS)
      static_cast<v4l2_requestbuffers *>(p)->count = 2;
    if (op == VIDIOC_QUERYBUF)
      static_cast<v4l2_buffer *>(p)->length = data.size();
    if (op == VIDIOC_DQBUF) {
      auto b = static_cast<v4l2_buffer *>(p);
      b->bytesused = data.size() - (short_frame ? 1 : 0);
      b->timestamp.tv_sec = 1;
      b->sequence = 42;
      b->flags = V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;
    }
    return 0;
  }
  int wait(int, int) override { return timeout ? 0 : 1; }
  void *map(int, size_t, int64_t) override { return data.data(); }
  int unmap(void *, size_t) override { return 0; }
  int closeDevice(int) override {
    ++close_count;
    return 0;
  }
};
static void v4l2() {
  auto fake = std::make_unique<FakeV4l2>();
  auto ptr = fake.get();
  V4l2FrameSource source("fake-not-device", std::move(fake));
  auto r = source.next();
  CHECK(r.frame && r.meta.camera_frame_id[0] == 42 &&
        r.frame->original[0].at<uint8_t>(0, 0) == 128);
  ptr->short_frame = true;
  CHECK(!source.next().error.empty());
  ptr->short_frame = false;
  ptr->timeout = true;
  CHECK(!source.next().error.empty());
}
#endif
static Json stress(int count) {
  CpuMotion cpu;
  FrameCache cache;
  auto original = frame(1);
  auto begin = Clock::now();
  for (int i = 1; i <= count; ++i) {
    auto f = std::make_shared<FramePair>();
    f->meta = original->meta;
    f->meta.pair_id = i;
    f->meta.timestamp_ns = int64_t(i) * 16000000;
    f->meta.eye_timestamp_ns = {f->meta.timestamp_ns, f->meta.timestamp_ns};
    f->original = original->original;
    f->search = original->search;
    cache.put(f);
    auto result = cpu.process(*f);
    CHECK(result.valid);
    CHECK(cache.size() <= 8);
    CHECK(LiveObjects::frames.load() <= 10);
    if (i > 1)
      CHECK(result.eyes[0].reference_id == static_cast<uint64_t>(i - 1));
  }
  return {
      {"pairs", count},
      {"elapsed_ms",
       std::chrono::duration<double, std::milli>(Clock::now() - begin).count()},
      {"frame_peak", LiveObjects::peak_frames.load()},
      {"cache_size", cache.size()}};
}
int main(int argc, char **argv) {
  Json report = {{"status", "running"}, {"tests", Json::array()}};
  try {
    if (argc > 1 && std::string(argv[1]) == "--stress") {
      report["stress"] = stress(argc > 2 ? std::stoi(argv[2]) : 10000);
    } else {
      std::vector<std::pair<std::string, std::function<void()>>> tests = {
          {"independent pixels and SHA256", pixels},
          {"reference failure/reset/config", reference},
          {"ROI mapping and retained ownership", roiCache},
          {"DMA codec/reordering/timeout", dma},
          {"vendor PCIe boundary mock/metadata/backpressure/reset",
           pcieBoundary},
          {"padded GRAY8 and corrupt inputs", files},
          {"bounded async delays/expiry/replacement", asynchronous}};
      tests.emplace_back("reject wrong-frame detections and backend clock",
                         forgedSource);
#ifdef __linux__
      tests.emplace_back("V4L2 syscall simulation", v4l2);
#endif
      for (auto &test : tests) {
        test.second();
        report["tests"].push_back({{"name", test.first}, {"status", "passed"}});
      }
    }
    CHECK(LiveObjects::frames == 0 && LiveObjects::contexts == 0);
    report["status"] = "passed";
    report["live_frames_end"] = LiveObjects::frames.load();
    report["live_contexts_end"] = LiveObjects::contexts.load();
    std::cout << report.dump(2) << '\n';
    return 0;
  } catch (const std::exception &e) {
    report["status"] = "failed";
    report["error"] = e.what();
    std::cout << report.dump(2) << '\n';
    return 1;
  }
}
