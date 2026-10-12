#include "pipeline/pipeline.hpp"
#include <iostream>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#ifdef __linux__
#include <linux/videodev2.h>
#endif
using namespace pipeline;
#define CHECK(x) do { if (!(x)) throw std::runtime_error("failed: " #x); } while (0)
template <class F> void rejects(F fn) {
  bool failed = false;
  try { fn(); } catch (const std::exception &) { failed = true; }
  CHECK(failed);
}
static bool same(const cv::Mat &a, const cv::Mat &b) {
  return a.size() == b.size() && a.type() == b.type() && cv::countNonZero(a != b) == 0;
}
static cv::Mat stereo() {
  cv::Mat image(EyeHeight, 2 * EyeWidth, CV_8U, cv::Scalar(16));
  image(cv::Rect(EyeWidth, 0, EyeWidth, EyeHeight)).setTo(235);
  image(cv::Rect(96, 112, 32, 40)).setTo(220);
  image(cv::Rect(EyeWidth + 200, 280, 48, 32)).setTo(25);
  return image;
}
static std::vector<uint8_t> jpeg(const cv::Mat &image) {
  std::vector<uint8_t> bytes;
  CHECK(cv::imencode(".jpg", image, bytes, {cv::IMWRITE_JPEG_QUALITY, 95}));
  return bytes;
}
static void codec() {
  const auto bytes = jpeg(stereo());
  const auto decoded = decodeMjpeg(bytes);
  CHECK(decoded.type() == CV_8UC1 && decoded.cols == 2560 && decoded.rows == 720);
  CHECK(decoded.at<uint8_t>(0, 0) == 16 && decoded.at<uint8_t>(0, 1280) == 235);
  CHECK(same(decoded, cv::imdecode(bytes, cv::IMREAD_GRAYSCALE | cv::IMREAD_IGNORE_ORIENTATION)));
  cv::Mat color;
  cv::cvtColor(stereo(), color, cv::COLOR_GRAY2BGR);
  CHECK(decodeMjpeg(jpeg(color)).size() == decoded.size());
  auto truncated = bytes;
  truncated.resize(truncated.size() - 17);
  rejects([&] { decodeMjpeg(truncated); });
  rejects([&] { decodeMjpeg({}); });
  rejects([&] { decodeMjpeg({0xff, 0xd8, 0xff, 0xd9}); });
  rejects([&] { decodeMjpeg({0xff, 0xd8, 0xff, 0xe0, 0xff, 0xff, 0xff, 0xd9}); });
  rejects([&] { decodeMjpeg(jpeg(cv::Mat(720, 1280, CV_8U, cv::Scalar(0)))); });
  std::vector<uint8_t> png;
  CHECK(cv::imencode(".png", stereo(), png));
  rejects([&] { decodeMjpeg(png); });
  auto concatenated = bytes;
  concatenated.insert(concatenated.end(), bytes.begin(), bytes.end());
  // File manifests specify one JPEG per entry, not a concatenated video.
  // The parser/decoder below must reject multiple images in one buffer.
  rejects([&] { decodeMjpeg(concatenated); });
}
static void files() {
  const auto root = std::filesystem::temp_directory_path() /
      utf8Path("pipeline-mjpeg-中文-" + std::to_string(monotonicNs()));
  std::filesystem::create_directories(root);
  const auto bytes = jpeg(stereo());
  writeBytes(root / utf8Path("左右拼接.jpg"), bytes);
  auto truncated = bytes;
  truncated.pop_back();
  writeBytes(root / "bad.jpg", truncated);
  auto entry = [&](int id, const char *name, const char *format) {
    return Json{{"pair_id", id}, {"timestamp_ns", int64_t(id) * 16000000},
                {"format", format}, {"width", 2560}, {"height", 720},
                {"file", name}, {"sha256", fileSha256(root / utf8Path(name))}};
  };
  Json frames = Json::array({entry(1, "左右拼接.jpg", "MJPG"),
                            entry(2, "bad.jpg", "MJPG"),
                            entry(3, "左右拼接.jpg", "MJPEG"),
                            entry(4, "左右拼接.jpg", "MJPG")});
  frames[3]["sha256"] = std::string(64, '0');
  writeText(root / "manifest.json", Json{{"schema_version", 1}, {"frames", frames}}.dump());
  FileFrameSource source(root / "manifest.json");
  CpuMotion cpu;
  const auto first = source.next();
  CHECK(first.frame && first.meta.pair_id == 1);
  const auto decoded = decodeMjpeg(bytes);
  for (int e = 0; e < 2; ++e) {
    CHECK(same(first.frame->original[e], decoded(cv::Rect(e * EyeWidth, 0, EyeWidth, EyeHeight))));
    CHECK(same(first.frame->search[e], average2x2(first.frame->original[e])));
    CHECK(same(cropRoi(*first.frame, static_cast<Eye>(e), cv::Point2d(640, 360)).image,
               first.frame->original[e](cv::Rect(512, 232, 256, 256))));
  }
  CHECK(!cpu.process(*first.frame).eyes[0].reference_valid);
  const auto bad = source.next();
  CHECK(!bad.frame && !bad.error.empty() && bad.meta.pair_id == 2);
  CHECK(bad.evidence["file_actual_bytes"] == truncated.size());
  const auto third = source.next();
  CHECK(third.frame && third.meta.timestamp_ns == 48000000);
  const auto motion = cpu.process(*third.frame);
  CHECK(motion.valid && motion.eyes[0].reference_id == 1 && motion.eyes[1].reference_id == 1);
  CHECK(source.next().error.find("SHA-256 mismatch") != std::string::npos);
  CHECK(source.next().end);
  source.seek(0);
  CHECK(source.next().frame);
  writeText(root / "export.json", Json{{"pixel_format", "MJPEG"}}.dump());
  writeText(root / "pairs.csv", "pair_index,left_index,right_index,left_requested_time_seconds,right_requested_time_seconds,pair_file\n1,1,1,0.016,0.016,左右拼接.jpg\n");
  const auto imported = importExportPackage(root, root / "imported.json");
  CHECK(imported["frames"][0]["format"] == "MJPG");
  CHECK(imported["frames"][0]["stride"] == 0);
  CHECK(FileFrameSource(root / "imported.json").next().frame);
  for (const auto &name : {"左右拼接.jpg", "bad.jpg", "manifest.json", "export.json", "pairs.csv", "imported.json"})
    std::filesystem::remove(root / utf8Path(name));
  std::filesystem::remove(root);
}
#ifdef __linux__
class Capture final : public V4l2Syscalls {
public:
  bool low_yuyv = true, corrupt = false, timeout = false, buffer_error = false;
  bool wrong_size = false, substitute = false, zero_interval = false;
  uint32_t actual = 0, sequence = 0;
  int exposure = -1, queued = 0, closed = 0;
  std::vector<uint32_t> requests;
  std::vector<uint8_t> encoded = jpeg(stereo());
  std::vector<uint8_t> buffer = std::vector<uint8_t>(EyeWidth * 4 * EyeHeight, 128);
  int openDevice(const std::string &) override { return 9; }
  int control(int, unsigned long op, void *arg) override {
    if (op == VIDIOC_QUERYCAP)
      static_cast<v4l2_capability *>(arg)->capabilities = V4L2_CAP_STREAMING | V4L2_CAP_VIDEO_CAPTURE;
    if (op == VIDIOC_S_FMT) {
      auto &p = static_cast<v4l2_format *>(arg)->fmt.pix;
      requests.push_back(p.pixelformat);
      actual = substitute ? V4L2_PIX_FMT_MJPEG : p.pixelformat;
      p.pixelformat = actual;
      p.bytesperline = actual == V4L2_PIX_FMT_YUYV ? EyeWidth * 4 : 0;
      if (wrong_size) p.width = 1280;
    }
    if (op == VIDIOC_S_PARM) {
      auto &interval = static_cast<v4l2_streamparm *>(arg)->parm.capture.timeperframe;
      CHECK(interval.numerator == 1 && interval.denominator == 60);
      if (zero_interval) interval = {0, 0};
      else interval = {1, actual == V4L2_PIX_FMT_YUYV && low_yuyv ? 5u : 60u};
    }
    if (op == VIDIOC_S_CTRL) {
      const auto c = static_cast<v4l2_control *>(arg);
      if (c->id == V4L2_CID_EXPOSURE_AUTO) CHECK(c->value == V4L2_EXPOSURE_MANUAL);
      if (c->id == V4L2_CID_EXPOSURE_ABSOLUTE) exposure = c->value;
    }
    if (op == VIDIOC_REQBUFS) {
      CHECK(static_cast<v4l2_requestbuffers *>(arg)->count == 4);
      static_cast<v4l2_requestbuffers *>(arg)->count = 2;
    }
    if (op == VIDIOC_QUERYBUF) static_cast<v4l2_buffer *>(arg)->length = buffer.size();
    if (op == VIDIOC_QBUF) ++queued;
    if (op == VIDIOC_DQBUF) {
      auto b = static_cast<v4l2_buffer *>(arg);
      if (actual == V4L2_PIX_FMT_MJPEG) std::copy(encoded.begin(), encoded.end(), buffer.begin());
      b->bytesused = actual == V4L2_PIX_FMT_MJPEG ? encoded.size() - (corrupt ? 1 : 0) : buffer.size();
      b->sequence = ++sequence;
      b->timestamp.tv_sec = 7;
      b->timestamp.tv_usec = sequence * 16667;
      b->flags = V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC | (buffer_error ? V4L2_BUF_FLAG_ERROR : 0);
    }
    return 0;
  }
  int wait(int, int ms) override { CHECK(ms == 500); return timeout ? 0 : 1; }
  void *map(int, size_t, int64_t) override { return buffer.data(); }
  int unmap(void *, size_t) override { return 0; }
  int closeDevice(int) override { ++closed; return 0; }
};
static void capture() {
  auto calls = std::make_unique<Capture>();
  auto ptr = calls.get();
  V4l2FrameSource source("fake", std::move(calls), 10);
  CHECK(ptr->requests == std::vector<uint32_t>({V4L2_PIX_FMT_YUYV, V4L2_PIX_FMT_MJPEG}));
  CHECK(ptr->exposure == 10);
  const auto first = source.next();
  CHECK(first.frame && first.meta.source == "uvc-v4l2-mjpg");
  CHECK(first.meta.timestamp_ns == 7016667000 && first.meta.camera_frame_id[0] == 1);
  CHECK(first.frame->original[0].at<uint8_t>(0, 0) == 16);
  CHECK(first.frame->original[1].at<uint8_t>(0, 0) == 235);
  const auto queued = ptr->queued;
  ptr->corrupt = true;
  CHECK(!source.next().frame && ptr->queued == queued + 1);
  ptr->corrupt = false;
  CHECK(source.next().frame);
  CHECK(first.frame->original[0].at<uint8_t>(0, 0) == 16);
  ptr->buffer_error = true;
  CHECK(!source.next().frame);
  ptr->buffer_error = false;
  ptr->timeout = true;
  CHECK(source.next().error.find("timeout") != std::string::npos);
  auto raw = std::make_unique<Capture>();
  auto rawptr = raw.get();
  rawptr->low_yuyv = false;
  V4l2FrameSource old("raw", std::move(raw), 10);
  CHECK(rawptr->requests.size() == 1 && old.next().meta.source == "uvc-v4l2");
  auto explicitCalls = std::make_unique<Capture>();
  auto explicitPtr = explicitCalls.get();
  V4l2FrameSource explicitSource("jpeg", std::move(explicitCalls), 10, "MJPG");
  CHECK(explicitPtr->requests == std::vector<uint32_t>({V4L2_PIX_FMT_MJPEG}));
  CHECK(explicitSource.next().frame);
  rejects([] { V4l2FrameSource s("bad", std::make_unique<Capture>(), 10, "YUYV"); });
  rejects([] { auto c = std::make_unique<Capture>(); c->wrong_size = true; V4l2FrameSource s("bad", std::move(c), 10); });
  rejects([] { auto c = std::make_unique<Capture>(); c->zero_interval = true; V4l2FrameSource s("bad", std::move(c), 10); });
  rejects([] { auto c = std::make_unique<Capture>(); c->substitute = true; V4l2FrameSource s("bad", std::move(c), 10, "YUYV"); });
}
#endif
int main() {
  try {
    codec();
    files();
#ifdef __linux__
    capture();
#endif
    CHECK(LiveObjects::frames == 0);
    std::cout << "MJPEG_INPUT_PASS codec_file_identity_split_roi_hash_recovery"
#ifdef __linux__
              << " v4l2_auto_fallback_60fps_exposure_requeue_timestamp"
#endif
              << '\n';
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "MJPEG_INPUT_FAIL " << e.what() << '\n';
    return 1;
  }
}
