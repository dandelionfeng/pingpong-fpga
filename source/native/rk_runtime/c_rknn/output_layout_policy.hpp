#pragma once
// Output-count policy shared by the RKNN session and host tests.
#include <cstdint>
#include <string>

namespace c_actual {
enum class OutputMode { kSingle, kRawHeads, kFlatDfl };

inline bool select_output_mode(uint32_t output_count, OutputMode *mode, std::string *error) {
  if (!mode) {
    if (error) *error = "output mode is null";
    return false;
  }
  switch (output_count) {
    case 1: *mode = OutputMode::kSingle; return true;
    case 6: *mode = OutputMode::kRawHeads; return true;
    case 8: *mode = OutputMode::kFlatDfl; return true;
    default:
      if (error) *error = "unsupported RKNN output count " + std::to_string(output_count) +
                          " (expected 1, 6 or 8)";
      return false;
  }
}
}  // namespace c_actual
