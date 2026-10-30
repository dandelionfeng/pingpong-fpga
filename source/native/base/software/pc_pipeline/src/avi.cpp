#include "pipeline/stereo.hpp"
#include <cstring>
namespace pipeline {
Json importStereoAvi(const Path &video, const Path &manifest) {
  if (std::filesystem::exists(manifest) ||
      std::filesystem::exists(manifest.parent_path() / "jpeg"))
    throw std::runtime_error(
        "AVI import requires fresh manifest and jpeg directory");
  auto bytes =
      readBytes(video); // bounded to 128 MiB; larger AVI needs streaming import
  auto tag = [&](size_t pos, const char *s) {
    return pos + 4 <= bytes.size() &&
           std::memcmp(bytes.data() + pos, s, 4) == 0;
  };
  auto u32 = [&](size_t p) -> uint32_t {
    if (p + 4 > bytes.size())
      throw std::runtime_error("truncated AVI header");
    return uint32_t(bytes[p]) | uint32_t(bytes[p + 1]) << 8 |
           uint32_t(bytes[p + 2]) << 16 | uint32_t(bytes[p + 3]) << 24;
  };
  if (!tag(0, "RIFF") || !tag(8, "AVI "))
    throw std::runtime_error("expected RIFF AVI");
  Json result = {
      {"schema_version", 1},
      {"mode", "file"},
      {"geometry_status", "real_stereo_geometry_requires_calibration"},
      {"frames", Json::array()}};
  uint32_t scale = 0, rate = 0, declared = 0;
  int width = 0, height = 0, stream = -1, streamCounter = 0;
  bool mjpg = false, truncated = uint64_t(u32(4)) + 8 > bytes.size();
  size_t frameIndex = 0;
  Json rejected = Json::array();
  std::function<void(size_t, size_t, bool, int)> walk;
  walk = [&](size_t begin, size_t end, bool movi, int depth) {
    if (depth > 8)
      throw std::runtime_error("AVI nesting exceeds limit");
    for (size_t pos = begin; pos + 8 <= end;) {
      uint32_t count = u32(pos + 4);
      size_t stop = pos + 8 + size_t(count);
      if (tag(pos, "LIST")) {
        if (count < 4)
          throw std::runtime_error("invalid AVI LIST");
        walk(pos + 12, std::min(stop, end), movi || tag(pos + 8, "movi"),
             depth + 1);
      } else if (tag(pos, "strh") && stop <= end && count >= 48) {
        int current = streamCounter++;
        if (tag(pos + 8, "vids")) {
          if (stream >= 0)
            throw std::runtime_error("multiple video streams unsupported");
          stream = current;
          mjpg = tag(pos + 12, "MJPG");
          scale = u32(pos + 28);
          rate = u32(pos + 32);
          declared = u32(pos + 40);
        }
      } else if (tag(pos, "avih") && stop <= end && count >= 40) {
        width = int(u32(pos + 40));
        height = int(u32(pos + 44));
      } else if (movi && bytes[pos] >= '0' && bytes[pos] <= '9' &&
                 bytes[pos + 1] >= '0' && bytes[pos + 1] <= '9' &&
                 bytes[pos + 2] == 'd' &&
                 (bytes[pos + 3] == 'b' || bytes[pos + 3] == 'c') &&
                 (bytes[pos] - '0') * 10 + bytes[pos + 1] - '0' == stream) {
        size_t index = frameIndex++;
        if (stop > end) {
          truncated = true;
          rejected.push_back(
              {{"frame_index", index}, {"reason", "truncated_packet"}});
        } else {
          if (!mjpg || !scale || !rate || width != 2 * EyeWidth ||
              height != EyeHeight)
            throw std::runtime_error(
                "expected single MJPG 2560x720 stream with rational FPS");
          std::vector<uint8_t> jpeg(bytes.begin() + pos + 8,
                                    bytes.begin() + stop);
          std::string error;
          try {
            const std::array<uint8_t, 2> eoi{255, 217};
            if (jpeg.size() < 4 || jpeg[0] != 255 || jpeg[1] != 216 ||
                std::search(jpeg.begin() + 2, jpeg.end(), eoi.begin(),
                            eoi.end()) == jpeg.end())
              throw std::runtime_error("incomplete_JPEG");
            decodeMjpeg(jpeg);
          } catch (const std::exception &e) {
            error = e.what();
          }
          if (!error.empty())
            rejected.push_back({{"frame_index", index}, {"reason", error}});
          else {
            Path rel = utf8Path("jpeg/" + std::to_string(index) + ".jpg");
            writeBytes(manifest.parent_path() / rel, jpeg);
            Meta m;
            m.pair_id = index + 1;
            m.timestamp_ns =
                int64_t(std::llround(double(index) * scale / rate * 1e9));
            m.eye_timestamp_ns = {m.timestamp_ns, m.timestamp_ns};
            m.camera_frame_id = {index, index};
            m.time_source =
                "avi_stream_index_times_scale_over_rate_not_device_timestamp";
            m.source = "real_stereo_avi";
            Json entry = metaJson(m);
            entry.update({{"format", "MJPG"},
                          {"width", width},
                          {"height", height},
                          {"file", pathUtf8(rel)},
                          {"sha256", sha256(jpeg)}});
            result["frames"].push_back(entry);
          }
        }
      }
      if (stop > end) {
        truncated = true;
        break;
      }
      pos = stop + (count % 2);
    }
  };
  walk(12, bytes.size(), false, 0);
  if (result["frames"].empty())
    throw std::runtime_error("AVI has no complete decodable frames");
  result["provenance"] = {
      {"video_path", pathUtf8(std::filesystem::absolute(video))},
      {"video_sha256", sha256(bytes)},
      {"actual_bytes", bytes.size()},
      {"declared_riff_bytes", uint64_t(u32(4)) + 8},
      {"declared_frames", declared},
      {"complete_frames", result["frames"].size()},
      {"rejected_packets", rejected},
      {"truncated", truncated},
      {"fps", double(rate) / scale},
      {"fps_numerator", rate},
      {"fps_denominator", scale},
      {"left_right_order", "stitched_left=physical_left_camera, "
                           "stitched_right=physical_right_camera"},
      {"sync_status", "stitched_same_packet; sensor_sync_not_measured"},
      {"decoded_pixel_format", "GRAY8_from_original_JPEG_no_reencoding"}};
  writeText(manifest, result.dump(2));
  return result;
}
} // namespace pipeline
