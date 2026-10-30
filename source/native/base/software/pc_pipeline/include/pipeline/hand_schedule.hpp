#pragma once
#include <atomic>
namespace pipeline {
// Experimental session-local latch. It changes invocation scheduling only.
// Source-aligned observations continue to come exclusively from actual graphs.
inline std::atomic<bool> handMaskConfirmed{false};
inline std::atomic<bool> handKinematicConfirmed{false};
}
