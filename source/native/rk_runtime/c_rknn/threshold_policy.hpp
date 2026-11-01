#pragma once
// Shared candidate-floor math for RKNN optimized/full DFL decoding.
//
// The optimized decoder may skip a row when its maximum class logit is below
// the logit corresponding to base_conf. The full-DFL path keeps every row and
// relies on the same YoloDetector confidence filter. Keep both paths at the
// same confidence semantics.
#include <cmath>
#include <limits>
#include <string>

namespace c_actual {

struct CandidateThreshold {
  float logit = -std::numeric_limits<float>::infinity();
  bool skip_all = false;
};

// base_conf < 0 means "no early filtering" (used by BallTrack and callers that
// do not pass a detector threshold). 0 and 1 are valid and must not produce
// log(0) or a division by zero.
inline bool candidate_threshold(float base_conf, CandidateThreshold *out, std::string *error) {
  if (!out) {
    if (error) *error = "candidate threshold output is null";
    return false;
  }
  out->logit = -std::numeric_limits<float>::infinity();
  out->skip_all = false;
  if (base_conf == -1.0f) return true;
  if (!std::isfinite(base_conf) || base_conf < 0.0f || base_conf > 1.0f) {
    if (error) *error = "base_conf must be finite and in [0,1]; got " + std::to_string(base_conf);
    return false;
  }
  if (base_conf == 0.0f) {
    out->logit = -std::numeric_limits<float>::infinity();
    return true;
  }
  if (base_conf == 1.0f) {
    out->logit = std::numeric_limits<float>::infinity();
    out->skip_all = true;
    return true;
  }
  out->logit = std::log(base_conf / (1.0f - base_conf));
  return true;
}

// The full-DFL path passes early_filter=false and must never skip a row here;
// YoloDetector applies the same base_conf after full decoding.
inline bool candidate_should_skip(float maximum_logit, const CandidateThreshold &threshold,
                                  bool early_filter) {
  return early_filter && (threshold.skip_all || maximum_logit < threshold.logit);
}

}  // namespace c_actual
