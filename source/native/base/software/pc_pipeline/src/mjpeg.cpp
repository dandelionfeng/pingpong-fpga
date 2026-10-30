#include "pipeline/pipeline.hpp"
#include <opencv2/imgcodecs.hpp>

namespace pipeline {
cv::Mat decodeMjpeg(const std::vector<uint8_t> &bytes) {
  // Check the encoded dimensions before allocation. imdecode also accepts
  // other image types and truncated JPEGs, which are not valid capture frames.
  if (bytes.size() < 4 || bytes.size() > 16 * 1024 * 1024 ||
      bytes[0] != 0xff || bytes[1] != 0xd8 ||
      bytes[bytes.size() - 2] != 0xff || bytes.back() != 0xd9)
    throw std::runtime_error("MJPEG incomplete/invalid JPEG frame (SOI/EOI or size)");
  size_t position = 2;
  bool dimensions = false, scan = false;
  while (position + 1 < bytes.size()) {
    if (bytes[position++] != 0xff)
      throw std::runtime_error("MJPEG invalid JPEG header marker");
    while (position < bytes.size() && bytes[position] == 0xff)
      ++position;
    if (position >= bytes.size())
      break;
    const auto marker = bytes[position++];
    if (marker == 0 || marker == 0xd8 || marker == 0xd9 ||
        marker == 0x01 || (marker >= 0xd0 && marker <= 0xd7) ||
        position + 2 > bytes.size())
      throw std::runtime_error("MJPEG invalid JPEG header");
    const size_t length = (size_t(bytes[position]) << 8) | bytes[position + 1];
    if (length < 2 || length > bytes.size() - position)
      throw std::runtime_error("MJPEG truncated JPEG header segment");
    if (marker == 0xc0 || marker == 0xc1 || marker == 0xc2) {
      if (dimensions || length < 8 || bytes[position + 2] != 8)
        throw std::runtime_error("MJPEG unsupported JPEG frame header");
      const int height = (int(bytes[position + 3]) << 8) | bytes[position + 4];
      const int width = (int(bytes[position + 5]) << 8) | bytes[position + 6];
      const int components = bytes[position + 7];
      if (width != 2 * EyeWidth || height != EyeHeight)
        throw std::runtime_error("MJPEG expected 2560x720 JPEG");
      if ((components != 1 && components != 3) ||
          length != size_t(8 + components * 3))
        throw std::runtime_error("MJPEG unsupported JPEG components");
      dimensions = true;
    }
    if (marker == 0xda) {
      scan = true;
      position += length;
      break;
    }
    position += length;
  }
  if (!dimensions || !scan)
    throw std::runtime_error("MJPEG missing JPEG frame/scan header");
  bool end = false;
  while (position < bytes.size()) {
    if (bytes[position++] != 0xff)
      continue;
    while (position < bytes.size() && bytes[position] == 0xff)
      ++position;
    if (position >= bytes.size())
      break;
    const auto marker = bytes[position++];
    if (marker == 0 || (marker >= 0xd0 && marker <= 0xd7))
      continue; // Entropy byte stuffing and restart markers.
    if (marker == 0xd9) {
      end = position == bytes.size();
      break;
    }
    if (marker == 0xd8 || position + 2 > bytes.size())
      throw std::runtime_error("MJPEG invalid JPEG scan marker");
    const size_t length = (size_t(bytes[position]) << 8) | bytes[position + 1];
    if (length < 2 || length > bytes.size() - position)
      throw std::runtime_error("MJPEG truncated JPEG scan segment");
    position += length; // Includes subsequent progressive scans/tables.
  }
  if (!end)
    throw std::runtime_error("MJPEG expected exactly one complete JPEG frame");
  // Ignore EXIF orientation: the calibrated left/right pixel geometry must
  // remain unchanged. No RGB round trip or brightness-range expansion.
  auto gray = cv::imdecode(bytes, cv::IMREAD_GRAYSCALE | cv::IMREAD_IGNORE_ORIENTATION);
  if (gray.empty() || gray.type() != CV_8UC1 ||
      gray.size() != cv::Size(2 * EyeWidth, EyeHeight))
    throw std::runtime_error("MJPEG grayscale decoding failed");
  return gray;
}
} // namespace pipeline
