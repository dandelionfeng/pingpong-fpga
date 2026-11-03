#include "dfl_flat_decoder.hpp"
#include "output_layout_policy.hpp"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include <vector>

using c_actual::CandidateThreshold;
using c_actual::FlatDflLayout;
using c_actual::decode_flat_dfl;
using c_actual::identify_flat_dfl;

static bool close(float a, float b) { return std::fabs(a - b) < 1e-4f; }

int main() {
  c_actual::OutputMode mode;
  std::string error;
  assert(c_actual::select_output_mode(1, &mode, &error) && mode == c_actual::OutputMode::kSingle);
  assert(c_actual::select_output_mode(6, &mode, &error) && mode == c_actual::OutputMode::kRawHeads);
  assert(c_actual::select_output_mode(8, &mode, &error) && mode == c_actual::OutputMode::kFlatDfl);
  assert(!c_actual::select_output_mode(2, &mode, &error));

  const std::vector<std::vector<int64_t>> shapes = {
      {1, 7, 18900}, {1, 64, 18900}, {1, 3, 18900}, {1, 64, 120, 120},
      {1, 128, 60, 60}, {1, 256, 30, 30}, {1, 4, 18900}, {1, 3, 18900}};
  FlatDflLayout layout;
  assert(identify_flat_dfl(shapes, &layout, &error));
  assert(layout.dfl_index == 1);
  assert(layout.class_index == 2);  // first 3-channel tensor, before "scores"
  assert(layout.classes == 3);
  assert(layout.anchors == 18900);

  auto bad = shapes;
  bad.pop_back();
  FlatDflLayout invalid_layout;
  assert(!identify_flat_dfl(bad, &invalid_layout, &error));

  auto duplicate = shapes;
  duplicate[7] = {1, 64, 18900};
  assert(!identify_flat_dfl(duplicate, &invalid_layout, &error));

  // Re-identify the valid model after the negative tests reset the output.
  assert(identify_flat_dfl(shapes, &layout, &error));

  constexpr size_t kAnchors = 18900;
  std::vector<float> dfl(64 * kAnchors, 0.0f);
  std::vector<float> logits(3 * kAnchors, 0.0f);
  std::vector<float> out((4 + 3) * kAnchors, 1.0f);
  CandidateThreshold no_filter;
  assert(c_actual::candidate_threshold(-1.0f, &no_filter, &error));
  decode_flat_dfl(dfl.data(), logits.data(), layout, no_filter, true, out.data());

  // Uniform 16-bin DFL -> distance 7.5; first P3 cell at (0.5,0.5), stride 8.
  assert(close(out[0], 4.0f));
  assert(close(out[kAnchors], 4.0f));
  assert(close(out[2 * kAnchors], 120.0f));
  assert(close(out[3 * kAnchors], 120.0f));
  assert(close(out[4 * kAnchors], 0.5f));
  assert(close(out[5 * kAnchors], 0.5f));
  assert(close(out[6 * kAnchors], 0.5f));

  CandidateThreshold skip_all;
  skip_all.logit = std::numeric_limits<float>::infinity();
  skip_all.skip_all = true;
  std::fill(out.begin(), out.end(), 0.0f);
  decode_flat_dfl(dfl.data(), logits.data(), layout, skip_all, true, out.data());
  for (float value : out) assert(value == 0.0f);

  CandidateThreshold zero;
  assert(c_actual::candidate_threshold(0.0f, &zero, &error));
  std::fill(out.begin(), out.end(), 0.0f);
  decode_flat_dfl(dfl.data(), logits.data(), layout, zero, true, out.data());
  assert(close(out[4 * kAnchors], 0.5f));

  std::printf("flat_dfl_test: PASS (8-output layout, DFL, single sigmoid, base_conf 0/1, release-safe decode)\n");
  return 0;
}
