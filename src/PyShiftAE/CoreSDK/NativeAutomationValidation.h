#pragma once
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace NativeAutomation {
constexpr const char* kRevision = "native-automation-20260912";
constexpr int kMaxSamples = 2048;
constexpr int kMaxKeys = 4096;
constexpr int kMaxSnapshotRows = 2000;

struct RationalTime {
    std::int32_t value;
    std::uint32_t scale;
    double seconds() const { return static_cast<double>(value) / scale; }
};

inline RationalTime timeFromSeconds(double seconds) {
    if (!std::isfinite(seconds) || std::abs(seconds) > 86400.0)
        throw std::invalid_argument("time must be finite and within +/-86400 seconds");
    // AE's numerator is signed 32-bit. Retain microseconds where possible,
    // and reduce precision only for long timelines instead of overflowing.
    std::uint32_t scale = 1000000;
    while (std::abs(seconds) * scale > (std::numeric_limits<std::int32_t>::max)() - 1.0)
        scale /= 10;
    return {static_cast<std::int32_t>(std::llround(seconds * scale)), scale};
}

inline void validateKeyTimes(const std::vector<double>& times) {
    if (times.empty() || times.size() > kMaxKeys)
        throw std::invalid_argument("keyframes must contain 1..4096 entries");
    double previous = -std::numeric_limits<double>::infinity();
    for (double t : times) {
        const auto actual = timeFromSeconds(t).seconds();
        if (actual <= previous)
            throw std::invalid_argument("keyframe times must increase after native time quantization");
        previous = actual;
    }
}
}
