#include "pipeline/pipeline.hpp"
#include <algorithm>
#include <cmath>
namespace pipeline {
cv::Mat integerGaussian(const cv::Mat &in) {
  if (in.empty() || in.type() != CV_8U)
    throw std::runtime_error("Gaussian needs GRAY8");
  cv::Mat horizontal(in.rows, in.cols, CV_16U), out(in.rows, in.cols, CV_8U);
  for (int y = 0; y < in.rows; ++y) {
    const auto s = in.ptr<uint8_t>(y);
    auto d = horizontal.ptr<uint16_t>(y);
    d[0] = 3 * s[0] + s[std::min(1, in.cols - 1)];
    // Bounds are handled once at each edge, leaving the interior vectorizable.
    for (int x = 1; x < in.cols - 1; ++x)
      d[x] = s[x - 1] + 2 * s[x] + s[x + 1];
    if (in.cols > 1)
      d[in.cols - 1] = s[in.cols - 2] + 3 * s[in.cols - 1];
  }
  for (int y = 0; y < in.rows; ++y) {
    const auto a = horizontal.ptr<uint16_t>(std::max(0, y - 1));
    const auto b = horizontal.ptr<uint16_t>(y);
    const auto c = horizontal.ptr<uint16_t>(std::min(in.rows - 1, y + 1));
    auto d = out.ptr<uint8_t>(y);
    for (int x = 0; x < in.cols; ++x)
      d[x] = static_cast<uint8_t>((a[x] + 2 * b[x] + c[x] + 8) >> 4);
  }
  return out;
}
cv::Mat binaryMorph(const cv::Mat &in, bool dilate) {
  if (in.empty() || in.type() != CV_8U)
    throw std::runtime_error("morphology needs binary GRAY8");
  // Bitwise OR/AND are separable. Keep the original behavior for every uint8
  // value, including non-binary diagnostic inputs. min/max morphology differs.
  cv::Mat padded, horizontal, vertical, out;
  cv::copyMakeBorder(in, padded, 0, 0, 1, 1, cv::BORDER_REPLICATE | cv::BORDER_ISOLATED);
  auto combine = [dilate](const cv::Mat &a, const cv::Mat &b, cv::Mat &dst) {
    if (dilate) cv::bitwise_or(a, b, dst);
    else cv::bitwise_and(a, b, dst);
  };
  combine(padded(cv::Rect(0, 0, in.cols, in.rows)),
          padded(cv::Rect(1, 0, in.cols, in.rows)), horizontal);
  combine(horizontal, padded(cv::Rect(2, 0, in.cols, in.rows)), horizontal);
  cv::copyMakeBorder(horizontal, vertical, 1, 1, 0, 0, cv::BORDER_REPLICATE);
  combine(vertical(cv::Rect(0, 0, in.cols, in.rows)),
          vertical(cv::Rect(0, 1, in.cols, in.rows)), out);
  combine(out, vertical(cv::Rect(0, 2, in.cols, in.rows)), out);
  return out;
}
std::vector<uint8_t> packMask(const cv::Mat &m) {
  if (m.empty() || m.type() != CV_8U || m.cols % 8)
    throw std::runtime_error("packed mask width must divide by 8");
  std::vector<uint8_t> bytes(static_cast<size_t>(m.rows) * m.cols / 8);
  for (int y = 0; y < m.rows; ++y) {
    auto row = m.ptr<uint8_t>(y);
    for (int x = 0; x < m.cols; ++x) {
      if (row[x] != 0 && row[x] != 255)
        throw std::runtime_error("mask pixel must be 0 or 255");
      if (row[x])
        bytes[static_cast<size_t>(y) * (m.cols / 8) + x / 8] |=
            static_cast<uint8_t>(1u << (x % 8));
    }
  }
  return bytes;
}

cv::Mat unpackMask(const std::vector<uint8_t> &b, int w, int h) {
  if (w <= 0 || h <= 0 || w % 8 || b.size() != static_cast<size_t>(w / 8) * h)
    throw std::runtime_error("packed mask length mismatch");
  cv::Mat m(h, w, CV_8U);
  for (int y = 0; y < h; ++y) {
    auto row = m.ptr<uint8_t>(y);
    for (int x = 0; x < w; ++x)
      row[x] = (b[static_cast<size_t>(y) * (w / 8) + x / 8] & (1u << (x % 8)))
                   ? 255
                   : 0;
  }
  return m;
}
MotionResult CpuMotion::process(const MotionInput &in) {
  MotionResult result;
  result.meta = in.meta;
  if (in.meta.config_version != config_.version) {
    result.valid = false;
    result.error = "configuration version mismatch";
    return result;
  }
  for (auto &im : in.search)
    if (im.type() != CV_8U ||
        im.size() != cv::Size(SearchWidth, SearchHeight)) {
      result.valid = false;
      result.error = "expected two 640x360 GRAY8 search images";
      return result;
    }
  for (int e = 0; e < 2; ++e) {
    if (!previous_[e].empty() &&
        (in.meta.pair_id <= reference_[e].pair_id ||
         in.meta.eye_timestamp_ns[e] <= reference_[e].eye_timestamp_ns[e])) {
      result.valid = false;
      result.error = "motion sequence is not increasing";
      return result;
    }
  }
  for (int e = 0; e < 2; ++e) {
    auto &r = result.eyes[e];
    r.reference_valid = !previous_[e].empty();
    r.reference_id = r.reference_valid ? reference_[e].pair_id : 0;
    r.reference_timestamp_ns =
        r.reference_valid ? reference_[e].eye_timestamp_ns[e] : 0;
    r.stages[0] = integerGaussian(in.search[e]);
    r.stages[1] = cv::Mat::zeros(SearchHeight, SearchWidth, CV_8U);
    r.stages[2] = cv::Mat::zeros(SearchHeight, SearchWidth, CV_8U);
    if (r.reference_valid) {
      cv::absdiff(r.stages[0], previous_[e], r.stages[1]);
      cv::compare(r.stages[1], config_.threshold, r.stages[2], cv::CMP_GT);
    }
    r.stages[3] = binaryMorph(r.stages[2], false);
    r.stages[4] = binaryMorph(r.stages[3], true);
    r.stages[5] = binaryMorph(r.stages[4], true);
    r.stages[6] = binaryMorph(r.stages[5], false);
  }
  // Commit both eyes after every stage succeeded. Notification delay does not
  // change this processing order.
  for (int e = 0; e < 2; ++e) {
    previous_[e] = result.eyes[e].stages[0];
    reference_[e] = in.meta;
  }
  result.completion_ns = monotonicNs();
  return result;
}
void CpuMotion::reset() {
  for (auto &p : previous_)
    p.release();
  reference_ = {};
}
void CpuMotion::configure(MotionConfig c) {
  if (c.threshold < 0 || c.threshold > 255 || c.version.empty())
    throw std::runtime_error("invalid motion configuration");
  reset();
  config_ = std::move(c);
}
static void put(std::vector<uint8_t> &b, uint64_t v, int n) {
  for (int i = 0; i < n; ++i)
    b.push_back(static_cast<uint8_t>(v >> (8 * i)));
}
static uint64_t take(const std::vector<uint8_t> &b, size_t &p, int n) {
  if (p + static_cast<size_t>(n) > b.size())
    throw std::runtime_error("short DMA descriptor");
  uint64_t v = 0;
  for (int i = 0; i < n; ++i)
    v |= uint64_t(b[p++]) << (8 * i);
  return v;
}
std::vector<uint8_t> serializeMotionInput(const MotionInput &in) {
  auto meta = metaJson(in.meta).dump();
  if (meta.size() > 65535)
    throw std::runtime_error("metadata exceeds DMA draft limit");
  std::vector<uint8_t> b{'A', 'M', '0', '1'};
  put(b, 1, 2);
  put(b, SearchWidth, 2);
  put(b, SearchHeight, 2);
  put(b, meta.size(), 2);
  put(b, 2 * SearchWidth * SearchHeight, 4);
  b.insert(b.end(), meta.begin(), meta.end());
  for (auto &m : in.search) {
    if (m.type() != CV_8U || m.size() != cv::Size(SearchWidth, SearchHeight))
      throw std::runtime_error("invalid DMA search image");
    for (int y = 0; y < m.rows; ++y)
      b.insert(b.end(), m.ptr<uint8_t>(y), m.ptr<uint8_t>(y) + m.cols);
  }
  return b;
}
MotionInput deserializeMotionInput(const std::vector<uint8_t> &b) {
  if (b.size() < 16 || std::string(b.begin(), b.begin() + 4) != "AM01")
    throw std::runtime_error("DMA magic mismatch");
  size_t p = 4;
  if (take(b, p, 2) != 1 || take(b, p, 2) != SearchWidth ||
      take(b, p, 2) != SearchHeight)
    throw std::runtime_error("DMA version/dimensions mismatch");
  size_t n = static_cast<size_t>(take(b, p, 2)),
         payload = static_cast<size_t>(take(b, p, 4));
  if (payload != 2 * SearchWidth * SearchHeight || p + n + payload != b.size())
    throw std::runtime_error("DMA length mismatch");
  MotionInput in;
  in.meta = parseMeta(Json::parse(b.begin() + p, b.begin() + p + n));
  p += n;
  for (auto &m : in.search) {
    m = cv::Mat(SearchHeight, SearchWidth, CV_8U);
    std::copy_n(b.data() + p, SearchWidth * SearchHeight, m.data);
    p += SearchWidth * SearchHeight;
  }
  return in;
}
} // namespace pipeline
