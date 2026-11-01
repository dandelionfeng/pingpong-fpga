// Repeatable unit test for the RKNN candidate-floor math (no RKNN/OpenCV needed).
#include "../threshold_policy.hpp"

#include <cmath>
#include <iostream>
#include <limits>
#include <string>

namespace {
int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    ++failures;
  }
}

void check_threshold(float base_conf, float expected, bool expected_skip) {
  c_actual::CandidateThreshold out;
  std::string error;
  const bool ok = c_actual::candidate_threshold(base_conf, &out, &error);
  expect(ok, "candidate_threshold(" + std::to_string(base_conf) + ") should succeed: " + error);
  if (!ok) return;
  expect(out.skip_all == expected_skip, "skip_all for " + std::to_string(base_conf));
  if (std::isfinite(expected)) {
    expect(std::fabs(out.logit - expected) < 1e-5f,
           "logit for " + std::to_string(base_conf) + ": got " + std::to_string(out.logit) +
               " expected " + std::to_string(expected));
    const float recovered = 1.0f / (1.0f + std::exp(-out.logit));
    expect(std::fabs(recovered - base_conf) < 1e-5f,
           "sigmoid(logit) must recover base_conf");
  } else if (std::isinf(expected) && expected < 0) {
    expect(std::isinf(out.logit) && out.logit < 0, "base_conf=0 must map to -inf");
  } else if (std::isinf(expected) && expected > 0) {
    expect(std::isinf(out.logit) && out.logit > 0, "base_conf=1 must map to +inf");
  }
}

void check_invalid(float base_conf) {
  c_actual::CandidateThreshold out;
  std::string error;
  expect(!c_actual::candidate_threshold(base_conf, &out, &error),
         "candidate_threshold(" + std::to_string(base_conf) + ") must fail");
  expect(!error.empty(), "invalid base_conf must set error text");
}
}  // namespace

int main() {
  check_threshold(0.02f, std::log(0.02f / 0.98f), false);
  check_threshold(0.005f, std::log(0.005f / 0.995f), false);
  check_threshold(0.0f, -std::numeric_limits<float>::infinity(), false);
  check_threshold(1.0f, std::numeric_limits<float>::infinity(), true);
  check_invalid(-0.1f);
  check_invalid(1.1f);
  check_invalid(std::numeric_limits<float>::quiet_NaN());
  check_invalid(std::numeric_limits<float>::infinity());

  c_actual::CandidateThreshold five_thousandths;
  std::string error;
  expect(c_actual::candidate_threshold(0.005f, &five_thousandths, &error), "0.005 setup");
  expect(c_actual::candidate_should_skip(-6.0f, five_thousandths, true),
         "optimized .005 must skip logit -6.0");
  expect(!c_actual::candidate_should_skip(-5.0f, five_thousandths, true),
         "optimized .005 must keep logit -5.0 (sigmoid > .005)");
  const float logit_001 = std::log(0.01f / 0.99f);
  expect(!c_actual::candidate_should_skip(logit_001, five_thousandths, true),
         "optimized .005 must keep a 0.01 candidate that old .02 would drop");
  expect(!c_actual::candidate_should_skip(-100.0f, five_thousandths, false),
         "full-DFL bypass must never skip in the decoder");

  // The full-DFL path will keep all rows; this test only verifies the logit
  // boundary. The YoloDetector confidence filter is the post-decode authority.
  c_actual::CandidateThreshold no_filter;
  expect(c_actual::candidate_threshold(-1.0f, &no_filter, &error), "sentinel -1 must disable early filtering");
  expect(std::isinf(no_filter.logit) && no_filter.logit < 0 && !no_filter.skip_all,
         "sentinel -1 must map to -inf without skip_all");

  if (failures) {
    std::cerr << failures << " threshold test(s) failed\n";
    return 1;
  }
  std::cout << "threshold_policy_test: PASS (0.02, 0.005, 0, 1, -0.1, 1.1, NaN, +inf, sentinel)\n";
  return 0;
}
