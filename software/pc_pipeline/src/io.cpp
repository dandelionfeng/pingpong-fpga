#include "pipeline/pipeline.hpp"
#include <algorithm>
#include <fstream>
#include <limits>
#include <opencv2/imgcodecs.hpp>
#include <sstream>

namespace pipeline {
std::string eyeName(Eye eye) { return eye == Eye::Left ? "left" : "right"; }
Path utf8Path(const std::string &s) { return std::filesystem::u8path(s); }
std::string pathUtf8(const Path &p) { return p.u8string(); }
std::string readText(const Path &p) {
  std::ifstream f(p, std::ios::binary);
  if (!f)
    throw std::runtime_error("cannot open: " + pathUtf8(p));
  return std::string(std::istreambuf_iterator<char>(f), {});
}
void writeText(const Path &p, const std::string &text) {
  if (!p.parent_path().empty())
    std::filesystem::create_directories(p.parent_path());
  std::ofstream f(p, std::ios::binary);
  if (!f)
    throw std::runtime_error("cannot write: " + pathUtf8(p));
  f << text;
  if (!f)
    throw std::runtime_error("write failed: " + pathUtf8(p));
}
std::vector<uint8_t> readBytes(const Path &p) {
  std::ifstream f(p, std::ios::binary | std::ios::ate);
  if (!f)
    throw std::runtime_error("cannot open: " + pathUtf8(p));
  auto n = f.tellg();
  if (n < 0 || n > 128 * 1024 * 1024)
    throw std::runtime_error("invalid input size: " + pathUtf8(p));
  std::vector<uint8_t> b(static_cast<size_t>(n));
  f.seekg(0);
  f.read(reinterpret_cast<char *>(b.data()),
         static_cast<std::streamsize>(b.size()));
  if (!f && !b.empty())
    throw std::runtime_error("short read: " + pathUtf8(p));
  return b;
}
void writeBytes(const Path &p, const std::vector<uint8_t> &b) {
  if (!p.parent_path().empty())
    std::filesystem::create_directories(p.parent_path());
  std::ofstream f(p, std::ios::binary);
  f.write(reinterpret_cast<const char *>(b.data()),
          static_cast<std::streamsize>(b.size()));
  if (!f)
    throw std::runtime_error("write failed: " + pathUtf8(p));
}
void writeImage(const Path &p, const cv::Mat &image) {
  std::vector<uint8_t> b;
  if (!cv::imencode(".png", image, b))
    throw std::runtime_error("PNG encoding failed");
  writeBytes(p, b);
}
int64_t monotonicNs() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             Clock::now().time_since_epoch())
      .count();
}
void LiveObjects::increment(std::atomic<int> &value, std::atomic<int> &peak) {
  int n = ++value;
  int old = peak.load();
  while (old < n && !peak.compare_exchange_weak(old, n)) {
  }
}
FramePair::FramePair() {
  LiveObjects::increment(LiveObjects::frames, LiveObjects::peak_frames);
}
FramePair::~FramePair() { --LiveObjects::frames; }
Json metaJson(const Meta &m) {
  return {{"pair_id", m.pair_id},
          {"timestamp_ns", m.timestamp_ns},
          {"eye_timestamp_ns", m.eye_timestamp_ns},
          {"camera_frame_id", m.camera_frame_id},
          {"config_version", m.config_version},
          {"calibration_version", m.calibration_version},
          {"model_version", m.model_version},
          {"time_source", m.time_source},
          {"source", m.source}};
}
Meta parseMeta(const Json &j) {
  auto integer = [](const Json &n, const std::string &name, bool timestamp) {
    if (!n.is_number_integer() || n < 0 ||
        (timestamp && n > std::numeric_limits<int64_t>::max()))
      throw std::runtime_error("invalid nonnegative integer: " + name);
  };
  integer(j.at("pair_id"), "pair_id", false);
  integer(j.at("timestamp_ns"), "timestamp_ns", true);
  if (j.at("pair_id") == 0)
    throw std::runtime_error("pair_id must be positive");
  for (const auto &name : {"eye_timestamp_ns", "camera_frame_id"})
    if (j.contains(name)) {
      if (!j[name].is_array() || j[name].size() != 2)
        throw std::runtime_error(std::string(name) + " needs two eyes");
      for (auto &n : j[name])
        integer(n, name, std::string(name) == "eye_timestamp_ns");
    }
  Meta m;
  m.pair_id = j.at("pair_id").get<uint64_t>();
  m.timestamp_ns = j.at("timestamp_ns").get<int64_t>();
  m.eye_timestamp_ns =
      j.value("eye_timestamp_ns",
              std::array<int64_t, 2>{m.timestamp_ns, m.timestamp_ns});
  m.camera_frame_id =
      j.value("camera_frame_id", std::array<uint64_t, 2>{m.pair_id, m.pair_id});
  m.config_version = j.value("config_version", m.config_version);
  m.calibration_version = j.value("calibration_version", m.calibration_version);
  m.model_version = j.value("model_version", m.model_version);
  m.time_source = j.value("time_source", m.time_source);
  m.source = j.value("source", m.source);
  return m;
}
cv::Mat extractY(const std::vector<uint8_t> &b, int width, int height,
                 size_t stride) {
  if (width <= 0 || height <= 0 || width % 2 ||
      stride < static_cast<size_t>(width) * 2 ||
      b.size() != stride * static_cast<size_t>(height))
    throw std::runtime_error("YUY2 dimensions/stride/length mismatch");
  cv::Mat y(height, width, CV_8U);
  for (int row = 0; row < height; ++row) {
    auto dst = y.ptr<uint8_t>(row);
    auto src = b.data() + row * stride;
    for (int x = 0; x < width; ++x)
      dst[x] = src[2 * x];
  }
  return y;
}
cv::Mat average2x2(const cv::Mat &in) {
  if (in.type() != CV_8U || in.rows % 2 || in.cols % 2 || in.empty())
    throw std::runtime_error("average2x2 needs even GRAY8");
  cv::Mat out(in.rows / 2, in.cols / 2, CV_8U);
  for (int y = 0; y < out.rows; ++y) {
    auto a = in.ptr<uint8_t>(2 * y), b = in.ptr<uint8_t>(2 * y + 1);
    auto d = out.ptr<uint8_t>(y);
    for (int x = 0; x < out.cols; ++x)
      d[x] = static_cast<uint8_t>(
          (a[2 * x] + a[2 * x + 1] + b[2 * x] + b[2 * x + 1] + 2) >> 2);
  }
  return out;
}
cv::Point2d searchToOriginal(cv::Point2d p) {
  return {2 * p.x + 0.5, 2 * p.y + 0.5};
}
cv::Rect searchBoxToOriginal(cv::Rect r) {
  return {2 * r.x, 2 * r.y, 2 * r.width, 2 * r.height};
}
Roi cropRoi(const FramePair &f, Eye eye, cv::Point2d c, int size, int pad) {
  if (size < 1 || size > 4096 || pad < 0 || pad > 255 || !std::isfinite(c.x) ||
      !std::isfinite(c.y) || std::abs(c.x) > 1e6 || std::abs(c.y) > 1e6)
    throw std::runtime_error("invalid ROI");
  Roi r;
  r.origin = {static_cast<int>(std::floor(c.x)) - size / 2,
              static_cast<int>(std::floor(c.y)) - size / 2};
  r.image = cv::Mat(size, size, CV_8U, cv::Scalar(pad));
  r.pair_id = f.meta.pair_id;
  r.eye = eye;
  r.padding_value = pad;
  auto &in = f.original[static_cast<int>(eye)];
  cv::Rect clipped = cv::Rect(r.origin, cv::Size(size, size)) &
                     cv::Rect(0, 0, in.cols, in.rows);
  if (clipped.area()) {
    r.valid = {clipped.x - r.origin.x, clipped.y - r.origin.y, clipped.width,
               clipped.height};
    in(clipped).copyTo(r.image(r.valid));
  }
  return r;
}
void FrameCache::put(FramePtr f) {
  slots_[next_] = std::move(f);
  next_ = (next_ + 1) % slots_.size();
}
FramePtr FrameCache::find(uint64_t id) const {
  for (auto &f : slots_)
    if (f && f->meta.pair_id == id)
      return f;
  return {};
}
void FrameCache::clear() {
  for (auto &f : slots_)
    f.reset();
  next_ = 0;
}
size_t FrameCache::size() const {
  return std::count_if(slots_.begin(), slots_.end(),
                       [](const auto &f) { return bool(f); });
}
static std::vector<std::string> csvRow(const std::string &row) {
  std::vector<std::string> values;
  std::string value;
  bool quoted = false;
  for (size_t i = 0; i < row.size(); ++i) {
    char ch = row[i];
    if (ch == '"') {
      if (quoted && i + 1 < row.size() && row[i + 1] == '"') {
        value += '"';
        ++i;
      } else
        quoted = !quoted;
    } else if (ch == ',' && !quoted) {
      values.push_back(value);
      value.clear();
    } else if (ch != '\r')
      value += ch;
  }
  if (quoted)
    throw std::runtime_error("unterminated CSV quote");
  values.push_back(value);
  return values;
}
static int64_t decimalNs(std::string text) {
  auto p = text.find('.');
  std::string integer = text.substr(0, p),
              fraction = p == std::string::npos ? "" : text.substr(p + 1);
  if (fraction.size() > 9) {
    if (fraction.substr(9).find_first_not_of('0') != std::string::npos)
      throw std::runtime_error("timestamp precision exceeds ns");
    fraction.resize(9);
  }
  while (fraction.size() < 9)
    fraction += '0';
  return std::stoll(integer) * 1000000000LL + std::stoll(fraction);
}
Json importExportPackage(const Path &folder, const Path &output) {
  auto description = Json::parse(readText(folder / "export.json"));
  const auto format = description.value("pixel_format", "");
  const bool mjpeg = format == "MJPG" || format == "MJPEG";
  if (format != "YUY2" && !mjpeg)
    throw std::runtime_error("export package must contain YUY2 or MJPEG");
  Json result = {
      {"schema_version", 1},
      {"mode", "file"},
      {"provenance", description},
      {"geometry_status", mjpeg ? description.value("geometry_status", "unverified_stereo")
                                  : "duplicated_monocular_not_calibrated_stereo"},
      {"frames", Json::array()}};
  std::istringstream csv(readText(folder / "pairs.csv"));
  std::string line;
  if (!std::getline(csv, line))
    throw std::runtime_error("empty pairs.csv");
  auto header = csvRow(line);
  if (header[0].size() > 2 && static_cast<unsigned char>(header[0][0]) == 239)
    header[0].erase(0, 3);
  while (std::getline(csv, line)) {
    if (line.empty())
      continue;
    auto values = csvRow(line);
    if (values.size() != header.size())
      throw std::runtime_error("CSV field count mismatch");
    Json row;
    for (size_t i = 0; i < header.size(); ++i)
      row[header[i]] = values[i];
    Path pair =
        std::filesystem::absolute(folder / utf8Path(row.at("pair_file")));
    Meta meta;
    meta.pair_id = std::stoull(row.at("pair_index").get<std::string>());
    meta.timestamp_ns = decimalNs(row.at("left_requested_time_seconds"));
    meta.eye_timestamp_ns = {meta.timestamp_ns,
                             decimalNs(row.at("right_requested_time_seconds"))};
    meta.camera_frame_id = {
        std::stoull(row.at("left_index").get<std::string>()),
        std::stoull(row.at("right_index").get<std::string>())};
    meta.time_source = description.value("time_source", "video_requested_time_not_device_capture");
    Json entry = metaJson(meta);
    entry.update({{"format", mjpeg ? "MJPG" : "YUY2"},
                  {"width", EyeWidth * 2},
                  {"height", EyeHeight},
                  {"stride", mjpeg ? 0 : EyeWidth * 4},
                  {"file", pathUtf8(pair)},
                  {"sha256", fileSha256(pair)}});
    result["frames"].push_back(entry);
  }
  if (result["frames"].empty())
    throw std::runtime_error("no pairs in package");
  writeText(output, result.dump(2));
  return result;
}
FileFrameSource::FileFrameSource(Path manifest, bool verify)
    : root_(std::filesystem::absolute(manifest).parent_path()),
      manifest_(Json::parse(readText(manifest))), verify_(verify) {
  if (manifest_.value("schema_version", 0) != 1)
    throw std::runtime_error("unsupported manifest schema");
  entries_ = manifest_.at("frames").get<std::vector<Json>>();
  validation_.resize(entries_.size());
  std::set<uint64_t> ids;
  std::array<int64_t, 2> last{std::numeric_limits<int64_t>::min(),
                              std::numeric_limits<int64_t>::min()};
  uint64_t last_id = 0;
  int64_t last_pair_time = -1;
  for (size_t i = 0; i < entries_.size(); ++i) {
    try {
      auto m = parseMeta(entries_[i]);
      if (m.timestamp_ns <= last_pair_time)
        throw std::runtime_error("non-increasing pair timestamp");
      if (!m.pair_id || !ids.insert(m.pair_id).second || m.pair_id <= last_id)
        throw std::runtime_error("duplicate/out-of-order pair_id");
      for (int e = 0; e < 2; ++e)
        if (m.eye_timestamp_ns[e] <= last[e])
          throw std::runtime_error("non-increasing eye timestamp");
      last = m.eye_timestamp_ns;
      last_id = m.pair_id;
      last_pair_time = m.timestamp_ns;
    } catch (const std::exception &e) {
      validation_[i] = e.what();
    }
  }
}
void FileFrameSource::seek(size_t i) {
  if (i > entries_.size())
    throw std::out_of_range("seek beyond manifest");
  index_ = i;
}
FrameRead FileFrameSource::next() {
  FrameRead r;
  r.index = index_;
  if (index_ >= entries_.size()) {
    r.end = true;
    return r;
  }
  auto i = index_++;
  try {
    r.evidence = {{"manifest_entry", entries_[i]}, {"entry_index", i}};
    r.meta = parseMeta(entries_[i]);
    if (!validation_[i].empty())
      throw std::runtime_error(validation_[i]);
    auto &j = entries_[i];
    r.evidence = {{"manifest_entry", j}, {"entry_index", i}};
    auto f = std::make_shared<FramePair>();
    f->meta = r.meta;
    std::string format = j.at("format");
    int w = j.at("width"), h = j.at("height");
    const bool mjpeg = format == "MJPG" || format == "MJPEG";
    size_t stride = mjpeg ? 0 : j.at("stride").get<size_t>();
    if (stride > 65536)
      throw std::runtime_error("stride exceeds version-1 input limit (65536)");
    auto load = [&](const char *key, const char *hash) {
      auto p = root_ / utf8Path(j.at(key));
      r.evidence[std::string(key) + "_actual_bytes"] =
          std::filesystem::file_size(p);
      if (mjpeg && std::filesystem::file_size(p) > 16 * 1024 * 1024)
        throw std::runtime_error("MJPEG file exceeds 16 MiB input limit");
      if (!mjpeg && std::filesystem::file_size(p) != stride * static_cast<size_t>(h))
        throw std::runtime_error("raw file length mismatch: " + pathUtf8(p));
      auto b = readBytes(p);
      r.evidence[std::string(key) + "_actual_bytes"] = b.size();
      if (verify_ && j.contains(hash) &&
          sha256(b) != j.at(hash).get<std::string>()) {
        r.evidence[std::string(key) + "_actual_sha256"] = sha256(b);
        throw std::runtime_error("SHA-256 mismatch: " + pathUtf8(p));
      }
      return b;
    };
    if (mjpeg) {
      if (w != 2 * EyeWidth || h != EyeHeight)
        throw std::runtime_error("expected 2560x720 MJPEG");
      auto y = decodeMjpeg(load("file", "sha256"));
      for (int e = 0; e < 2; ++e)
        f->original[e] = y(cv::Rect(e * EyeWidth, 0, EyeWidth, EyeHeight)).clone();
    } else if (format == "YUY2") {
      if (w != 2 * EyeWidth || h != EyeHeight)
        throw std::runtime_error("expected 2560x720 YUY2");
      auto y = extractY(load("file", "sha256"), w, h, stride);
      for (int e = 0; e < 2; ++e)
        f->original[e] =
            y(cv::Rect(e * EyeWidth, 0, EyeWidth, EyeHeight)).clone();
    } else if (format == "GRAY8") {
      if (w != EyeWidth || h != EyeHeight || stride < static_cast<size_t>(w))
        throw std::runtime_error("expected 1280x720 GRAY8");
      for (int e = 0; e < 2; ++e) {
        auto b = load(e ? "right_file" : "left_file",
                      e ? "right_sha256" : "left_sha256");
        if (b.size() != stride * static_cast<size_t>(h))
          throw std::runtime_error("GRAY8 length mismatch");
        f->original[e] = cv::Mat(h, w, CV_8U, b.data(), stride).clone();
      }
    } else
      throw std::runtime_error("unsupported pixel format");
    for (int e = 0; e < 2; ++e)
      f->search[e] = average2x2(f->original[e]);
    r.frame = std::move(f);
    r.evidence = Json::object();
  } catch (const std::exception &e) {
    r.error = e.what();
  }
  return r;
}
} // namespace pipeline
