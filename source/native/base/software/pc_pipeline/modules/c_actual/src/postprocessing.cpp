#include "c_perception_engine.hpp"

#include <algorithm>
#include <cmath>

namespace c_actual {
namespace postprocess {

Box unletterbox(float cx, float cy, float w, float h, float confidence, int class_id,
                float scale, int pad_x, int pad_y, int image_w, int image_h) {
  // Undo: letterbox(x) = x * scale + pad, so x = (letterbox(x) - pad) / scale.
  const float inv = (scale > 0.f) ? (1.f / scale) : 0.f;
  const float x1 = (cx - w * 0.5f - static_cast<float>(pad_x)) * inv;
  const float y1 = (cy - h * 0.5f - static_cast<float>(pad_y)) * inv;
  const float x2 = (cx + w * 0.5f - static_cast<float>(pad_x)) * inv;
  const float y2 = (cy + h * 0.5f - static_cast<float>(pad_y)) * inv;

  Box box;
  box.x = std::max(0.f, std::min(x1, static_cast<float>(image_w)));
  box.y = std::max(0.f, std::min(y1, static_cast<float>(image_h)));
  const float clamped_x2 = std::max(0.f, std::min(x2, static_cast<float>(image_w)));
  const float clamped_y2 = std::max(0.f, std::min(y2, static_cast<float>(image_h)));
  box.w = std::max(0.f, clamped_x2 - box.x);
  box.h = std::max(0.f, clamped_y2 - box.y);
  box.confidence = confidence;
  box.class_id = class_id;
  return box;
}

float iou(const Box &a, const Box &b) {
  const float ax2 = a.x + a.w, ay2 = a.y + a.h;
  const float bx2 = b.x + b.w, by2 = b.y + b.h;
  const float ix1 = std::max(a.x, b.x);
  const float iy1 = std::max(a.y, b.y);
  const float ix2 = std::min(ax2, bx2);
  const float iy2 = std::min(ay2, by2);
  const float iw = std::max(0.f, ix2 - ix1);
  const float ih = std::max(0.f, iy2 - iy1);
  const float inter = iw * ih;
  const float area_a = a.w * a.h;
  const float area_b = b.w * b.h;
  const float uni = area_a + area_b - inter;
  if (uni <= 0.f) return 0.f;
  return inter / uni;
}

std::vector<Box> nms(std::vector<Box> boxes, float iou_threshold, int max_det) {
  std::stable_sort(boxes.begin(), boxes.end(),
                   [](const Box &a, const Box &b) { return a.confidence > b.confidence; });
  std::vector<Box> kept;
  std::vector<char> suppressed(boxes.size(), 0);
  for (size_t i = 0; i < boxes.size(); ++i) {
    if (suppressed[i]) continue;
    kept.push_back(boxes[i]);
    if (static_cast<int>(kept.size()) >= max_det) break;
    for (size_t j = i + 1; j < boxes.size(); ++j) {
      if (suppressed[j]) continue;
      if (boxes[j].class_id != boxes[i].class_id) continue;
      if (iou(boxes[i], boxes[j]) > iou_threshold) suppressed[j] = 1;
    }
  }
  return kept;
}

}  // namespace postprocess
}  // namespace c_actual
