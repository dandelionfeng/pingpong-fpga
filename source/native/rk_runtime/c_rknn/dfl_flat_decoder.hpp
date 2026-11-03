#pragma once
// RKNN 8-output DFL layout adapter.
//
// The delivered V3 DFL RKNN models expose eight tensors:
//   [1,7,18900]      concat box+score (ignored: mixed quantisation)
//   [1,64,18900]     DFL 4 sides x 16 bins (used)
//   [1,3,18900]      class logits before sigmoid (used, first 3-channel output)
//   [1,64,120,120]   P3 intermediate (ignored)
//   [1,128,60,60]    P4 intermediate (ignored)
//   [1,256,30,30]    P5 intermediate (ignored)
//   [1,4,18900]      decoded boxes (ignored: prefer DFL)
//   [1,3,18900]      sigmoid scores (ignored: avoids double sigmoid)
//
// Only the DFL distribution and the first 3-channel logits tensor are decoded.
// Keeping this policy in a small header makes the layout selection and the DFL
// math testable on x86 without an RKNN runtime.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

#include "threshold_policy.hpp"

namespace c_actual {

struct FlatDflLayout {
  int dfl_index = -1;
  int class_index = -1;
  int classes = 3;
  std::size_t anchors = 0;
};

// Shapes are canonical NCHW dimensions. The first 3-channel tensor wins:
// on the delivered graph index 2 is the pre-sigmoid class-logit tensor, while
// index 7 is the already-sigmoid "scores" tensor. Choosing the first one avoids
// a second sigmoid.
inline bool identify_flat_dfl(const std::vector<std::vector<int64_t>> &shapes,
                              FlatDflLayout *layout, std::string *error) {
  if (!layout) {
    if (error) *error = "flat DFL layout output is null";
    return false;
  }
  *layout = FlatDflLayout{};
  if (shapes.size() != 8) {
    if (error) *error = "8-output DFL model expected, got " + std::to_string(shapes.size()) + " outputs";
    return false;
  }
  int dfl = -1;
  std::size_t anchors = 0;
  for (std::size_t i = 0; i < shapes.size(); ++i) {
    const auto &s = shapes[i];
    if (s.size() == 3 && s[0] == 1 && s[1] == 64 && s[2] > 0) {
      if (dfl >= 0) {
        if (error) *error = "multiple 64-channel DFL outputs";
        return false;
      }
      dfl = static_cast<int>(i);
      anchors = static_cast<std::size_t>(s[2]);
    }
  }
  if (dfl < 0) {
    if (error) *error = "no [1,64,N] DFL distribution output";
    return false;
  }
  int cls = -1;
  for (std::size_t i = 0; i < shapes.size(); ++i) {
    const auto &s = shapes[i];
    if (s.size() == 3 && s[0] == 1 && s[1] == 3 && static_cast<std::size_t>(s[2]) == anchors) {
      cls = static_cast<int>(i);  // first 3-channel tensor: pre-sigmoid logits
      break;
    }
  }
  if (cls < 0) {
    if (error) *error = "no [1,3,N] class-logit output matching the DFL anchor count";
    return false;
  }
  // 18900 = 120^2 + 60^2 + 30^2 at 960 input.
  if (anchors != 120u * 120u + 60u * 60u + 30u * 30u) {
    if (error) *error = "unexpected DFL anchor count " + std::to_string(anchors);
    return false;
  }
  layout->dfl_index = dfl;
  layout->class_index = cls;
  layout->classes = 3;
  layout->anchors = anchors;
  return true;
}

// Decode [64,N] DFL logits and [3,N] pre-sigmoid class logits into the same
// [4+classes,N] layout used by YoloDetector. Rows below the configured early
// candidate floor are left as zeros; YoloDetector applies the same base_conf
// after the full decode, matching the existing 1/6-output behaviour.
inline void decode_flat_dfl(const float *dfl, const float *logits,
                            const FlatDflLayout &layout,
                            const CandidateThreshold &threshold,
                            bool early_filter, float *output) {
  constexpr int kSides[3] = {120, 60, 30};
  constexpr int kStrides[3] = {8, 16, 32};
  const std::size_t anchors = layout.anchors;
  const int classes = layout.classes;
  std::size_t offset = 0;
  for (int scale = 0; scale < 3; ++scale) {
    const int side = kSides[scale];
    const int stride = kStrides[scale];
    const std::size_t plane = static_cast<std::size_t>(side) * side;
    for (std::size_t pixel = 0; pixel < plane; ++pixel) {
      const std::size_t j = offset + pixel;
      float maximum_logit = logits[pixel];
      for (int c = 1; c < classes; ++c)
        maximum_logit = std::max(maximum_logit, logits[static_cast<std::size_t>(c) * anchors + j]);
      if (candidate_should_skip(maximum_logit, threshold, early_filter)) continue;

      // sigmoid exactly once, on the pre-sigmoid class logits.
      for (int c = 0; c < classes; ++c) {
        const float logit = logits[static_cast<std::size_t>(c) * anchors + j];
        output[static_cast<std::size_t>(4 + c) * anchors + j] = 1.0f / (1.0f + std::exp(-logit));
      }

      float d[4];
      for (int k = 0; k < 4; ++k) {
        float maximum = -std::numeric_limits<float>::infinity();
        for (int bin = 0; bin < 16; ++bin)
          maximum = std::max(maximum, dfl[static_cast<std::size_t>(k * 16 + bin) * anchors + j]);
        float sum = 0.0f, weighted = 0.0f;
        for (int bin = 0; bin < 16; ++bin) {
          const float v = std::exp(dfl[static_cast<std::size_t>(k * 16 + bin) * anchors + j] - maximum);
          sum += v;
          weighted += bin * v;
        }
        d[k] = weighted / sum;
      }
      const float x = static_cast<float>(pixel % static_cast<std::size_t>(side)) + 0.5f;
      const float y = static_cast<float>(pixel / static_cast<std::size_t>(side)) + 0.5f;
      output[j] = (x + (d[2] - d[0]) * 0.5f) * stride;
      output[anchors + j] = (y + (d[3] - d[1]) * 0.5f) * stride;
      output[2 * anchors + j] = (d[0] + d[2]) * stride;
      output[3 * anchors + j] = (d[1] + d[3]) * stride;
    }
    offset += plane;
  }
}

}  // namespace c_actual
