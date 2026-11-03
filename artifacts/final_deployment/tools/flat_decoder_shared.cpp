// Host-only shared library exposing the production flat-DFL decoder for
// numerical regression against the Python reference. It has no RKNN dependency.
#include "dfl_flat_decoder.hpp"

extern "C" int c_flat_decode(const float *dfl, const float *logits, float *out,
                             int anchors, float base_conf, int early_filter) {
  if (!dfl || !logits || !out || anchors <= 0) return 1;
  c_actual::FlatDflLayout layout;
  layout.dfl_index = 0;
  layout.class_index = 1;
  layout.classes = 3;
  layout.anchors = static_cast<std::size_t>(anchors);
  c_actual::CandidateThreshold threshold;
  std::string error;
  if (!c_actual::candidate_threshold(base_conf, &threshold, &error)) return 2;
  c_actual::decode_flat_dfl(dfl, logits, layout, threshold, early_filter != 0, out);
  return 0;
}
