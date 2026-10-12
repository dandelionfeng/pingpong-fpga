#include "pipeline/pipeline.hpp"
#ifdef __linux__
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
namespace pipeline {
class NativeCalls final : public V4l2Syscalls {
public:
  int openDevice(const std::string &p) override {
    return ::open(p.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
  }
  int control(int fd, unsigned long request, void *arg) override {
    int r;
    do {
      r = ::ioctl(fd, request, arg);
    } while (r < 0 && errno == EINTR);
    return r;
  }
  int wait(int fd, int ms) override {
    pollfd p{fd, POLLIN, 0};
    int r;
    do {
      r = ::poll(&p, 1, ms);
    } while (r < 0 && errno == EINTR);
    return r > 0 && (p.revents & POLLIN) ? 1 : r == 0 ? 0 : -1;
  }
  void *map(int fd, size_t size, int64_t offset) override {
    return ::mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
                  offset);
  }
  int unmap(void *p, size_t size) override { return ::munmap(p, size); }
  int closeDevice(int fd) override { return ::close(fd); }
};
std::unique_ptr<V4l2Syscalls> nativeV4l2Syscalls() {
  return std::make_unique<NativeCalls>();
}
V4l2FrameSource::V4l2FrameSource(std::string device,
                                 std::unique_ptr<V4l2Syscalls> calls,
                                 int exposure, std::string pixelFormat)
    : calls_(std::move(calls)) {
  try {
    if (!calls_)
      throw std::runtime_error("V4L2 syscall boundary unavailable");
    fd_ = calls_->openDevice(device);
    if (fd_ < 0)
      throw std::runtime_error("V4L2 open failed: " + device);
    auto ctl = [&](unsigned long r, void *a, const char *reason) {
      if (calls_->control(fd_, r, a) < 0)
        throw std::runtime_error(reason);
    };
    v4l2_capability cap{};
    ctl(VIDIOC_QUERYCAP, &cap, "V4L2 QUERYCAP failed");
    auto caps = (cap.capabilities & V4L2_CAP_DEVICE_CAPS) ? cap.device_caps
                                                          : cap.capabilities;
    if (!(caps & V4L2_CAP_VIDEO_CAPTURE) || !(caps & V4L2_CAP_STREAMING))
      throw std::runtime_error("V4L2 capture/streaming unsupported");
    std::vector<uint32_t> formats;
    if (pixelFormat == "auto")
      formats = {V4L2_PIX_FMT_YUYV, V4L2_PIX_FMT_MJPEG};
    else if (pixelFormat == "MJPG" || pixelFormat == "MJPEG")
      formats = {V4L2_PIX_FMT_MJPEG};
    else if (pixelFormat == "YUYV" || pixelFormat == "YUY2")
      formats = {V4L2_PIX_FMT_YUYV};
    else
      throw std::runtime_error("V4L2 pixel_format must be auto, YUYV or MJPG");
    std::string failure;
    for (const auto requested : formats) {
      try {
        v4l2_format format{};
        format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        format.fmt.pix.width = EyeWidth * 2;
        format.fmt.pix.height = EyeHeight;
        format.fmt.pix.pixelformat = requested;
        format.fmt.pix.field = V4L2_FIELD_NONE;
        ctl(VIDIOC_S_FMT, &format, "V4L2 S_FMT failed");
        const auto actual = format.fmt.pix.pixelformat;
        if (format.fmt.pix.width != EyeWidth * 2 ||
            format.fmt.pix.height != EyeHeight ||
            (actual != V4L2_PIX_FMT_YUYV && actual != V4L2_PIX_FMT_MJPEG) ||
            (pixelFormat != "auto" && actual != requested) ||
            (actual == V4L2_PIX_FMT_YUYV && format.fmt.pix.bytesperline < EyeWidth * 4))
          throw std::runtime_error("V4L2 negotiated format is not 2560x720 YUYV/MJPG");
        v4l2_streamparm parm{};
        parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        parm.parm.capture.timeperframe = {1, 60};
        ctl(VIDIOC_S_PARM, &parm, "V4L2 frame interval control failed");
        const auto interval = parm.parm.capture.timeperframe;
        if (!interval.numerator || !interval.denominator ||
            uint64_t(interval.numerator) * 60 != interval.denominator)
          throw std::runtime_error("V4L2 device did not negotiate 60 fps");
        pixel_format_ = actual;
        stride_ = actual == V4L2_PIX_FMT_YUYV ? format.fmt.pix.bytesperline : 0;
        break;
      } catch (const std::exception &e) {
        failure += std::string(requested == V4L2_PIX_FMT_MJPEG ? "MJPG: " : "YUYV: ") + e.what() + "; ";
      }
    }
    if (!pixel_format_)
      throw std::runtime_error("V4L2 capture negotiation failed: " + failure);
    v4l2_control c{};
    c.id = V4L2_CID_EXPOSURE_AUTO;
    c.value = V4L2_EXPOSURE_MANUAL;
    ctl(VIDIOC_S_CTRL, &c, "manual exposure unavailable");
    c.id = V4L2_CID_EXPOSURE_ABSOLUTE;
    c.value = exposure;
    ctl(VIDIOC_S_CTRL, &c, "exposure setting failed");
    v4l2_requestbuffers req{};
    req.count = 4;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    ctl(VIDIOC_REQBUFS, &req, "V4L2 REQBUFS failed");
    if (req.count < 2 || req.count > 64)
      throw std::runtime_error("invalid V4L2 buffer pool");
    for (unsigned i = 0; i < req.count; ++i) {
      v4l2_buffer b{};
      b.type = req.type;
      b.memory = req.memory;
      b.index = i;
      ctl(VIDIOC_QUERYBUF, &b, "V4L2 QUERYBUF failed");
      void *p = calls_->map(fd_, b.length, b.m.offset);
      if (p == MAP_FAILED || !p)
        throw std::runtime_error("V4L2 mmap failed");
      buffers_.push_back({p, b.length});
      ctl(VIDIOC_QBUF, &b, "V4L2 QBUF failed");
    }
    auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    ctl(VIDIOC_STREAMON, &type, "V4L2 STREAMON failed");
  } catch (...) {
    cleanup();
    throw;
  }
}
void V4l2FrameSource::cleanup() {
  if (fd_ >= 0) {
    auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    calls_->control(fd_, VIDIOC_STREAMOFF, &type);
    for (auto &b : buffers_)
      calls_->unmap(b.data, b.size);
    buffers_.clear();
    calls_->closeDevice(fd_);
    fd_ = -1;
  }
}
V4l2FrameSource::~V4l2FrameSource() { cleanup(); }
FrameRead V4l2FrameSource::next() {
  FrameRead r;
  bool dequeued = false;
  v4l2_buffer b{};
  b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  b.memory = V4L2_MEMORY_MMAP;
  try {
    int ready = calls_->wait(fd_, 500);
    if (ready == 0)
      throw std::runtime_error("V4L2 capture timeout");
    if (ready < 0)
      throw std::runtime_error("V4L2 device disconnected/poll error");
    if (calls_->control(fd_, VIDIOC_DQBUF, &b) < 0)
      throw std::runtime_error("V4L2 DQBUF failed");
    dequeued = true;
    r.meta.pair_id = ++pair_;
    r.meta.camera_frame_id = {b.sequence, b.sequence};
    r.meta.timestamp_ns = int64_t(b.timestamp.tv_sec) * 1000000000LL +
                          int64_t(b.timestamp.tv_usec) * 1000;
    r.meta.eye_timestamp_ns = {r.meta.timestamp_ns, r.meta.timestamp_ns};
    const bool mjpeg = pixel_format_ == V4L2_PIX_FMT_MJPEG;
    r.meta.source = mjpeg ? "uvc-v4l2-mjpg" : "uvc-v4l2";
    r.meta.time_source = (b.flags & V4L2_BUF_FLAG_TIMESTAMP_MASK) ==
                                 V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC
                             ? "v4l2_buffer_monotonic"
                             : "v4l2_buffer_clock_unverified";
    size_t expected = stride_ * EyeHeight;
    r.evidence = {{"capture_format", mjpeg ? "MJPG" : "YUYV"},
                  {"bytesused", b.bytesused}, {"sequence", b.sequence}};
    if (b.index >= buffers_.size() || !b.bytesused ||
        (!mjpeg && b.bytesused < expected) ||
        (mjpeg && b.bytesused > 16 * 1024 * 1024) ||
        b.bytesused > buffers_[b.index].size || (b.flags & V4L2_BUF_FLAG_ERROR))
      throw std::runtime_error("V4L2 short/error capture buffer");
    auto begin = static_cast<uint8_t *>(buffers_[b.index].data);
    auto y = mjpeg ? decodeMjpeg(std::vector<uint8_t>(begin, begin + b.bytesused))
                   : extractY(std::vector<uint8_t>(begin, begin + expected),
                              EyeWidth * 2, EyeHeight, stride_);
    auto f = std::make_shared<FramePair>();
    f->meta = r.meta;
    for (int e = 0; e < 2; ++e) {
      f->original[e] =
          y(cv::Rect(e * EyeWidth, 0, EyeWidth, EyeHeight)).clone();
      f->search[e] = average2x2(f->original[e]);
    }
    r.frame = f;
  } catch (const std::exception &e) {
    r.error = e.what();
  }
  if (dequeued && calls_->control(fd_, VIDIOC_QBUF, &b) < 0) {
    r.frame.reset();
    r.error = "V4L2 requeue failed";
  }
  return r;
}
} // namespace pipeline
#else
namespace pipeline {
std::unique_ptr<V4l2Syscalls> nativeV4l2Syscalls() { return {}; }
V4l2FrameSource::V4l2FrameSource(std::string, std::unique_ptr<V4l2Syscalls>,
                                 int, std::string) {
  throw std::runtime_error("V4L2 is Linux-only; use file input on Windows");
}
V4l2FrameSource::~V4l2FrameSource() = default;
void V4l2FrameSource::cleanup() {}
FrameRead V4l2FrameSource::next() {
  return {{}, {}, "V4L2 unavailable on Windows", true, 0};
}
} // namespace pipeline
#endif
