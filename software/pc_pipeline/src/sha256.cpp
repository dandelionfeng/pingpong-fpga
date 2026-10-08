#include "pipeline/pipeline.hpp"
#include <cstring>
#include <fstream>
#include <iomanip>
#include <sstream>
namespace pipeline {
namespace {
constexpr uint32_t K[] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
uint32_t rotate(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
struct Sha {
  uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  uint8_t buffer[64]{};
  size_t used = 0;
  uint64_t total = 0;
  void block(const uint8_t *p) {
    uint32_t w[64]{};
    for (int i = 0; i < 16; ++i)
      w[i] = (uint32_t(p[4 * i]) << 24) | (uint32_t(p[4 * i + 1]) << 16) |
             (uint32_t(p[4 * i + 2]) << 8) | p[4 * i + 3];
    for (int i = 16; i < 64; ++i) {
      auto x = w[i - 15], y = w[i - 2];
      w[i] = w[i - 16] + (rotate(x, 7) ^ rotate(x, 18) ^ (x >> 3)) + w[i - 7] +
             (rotate(y, 17) ^ rotate(y, 19) ^ (y >> 10));
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5],
             g = h[6], hh = h[7];
    for (int i = 0; i < 64; ++i) {
      uint32_t t1 = hh + (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) +
                    ((e & f) ^ (~e & g)) + K[i] + w[i];
      uint32_t t2 = (rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)) +
                    ((a & b) ^ (a & c) ^ (b & c));
      hh = g;
      g = f;
      f = e;
      e = d + t1;
      d = c;
      c = b;
      b = a;
      a = t1 + t2;
    }
    uint32_t values[] = {a, b, c, d, e, f, g, hh};
    for (int i = 0; i < 8; ++i)
      h[i] += values[i];
  }
  void update(const uint8_t *p, size_t n) {
    total += n;
    while (n) {
      size_t count = std::min(n, 64 - used);
      std::memcpy(buffer + used, p, count);
      used += count;
      p += count;
      n -= count;
      if (used == 64) {
        block(buffer);
        used = 0;
      }
    }
  }
  std::string finish() {
    uint64_t bits = total * 8;
    uint8_t end = 128;
    update(&end, 1);
    uint8_t zero = 0;
    while (used != 56)
      update(&zero, 1);
    uint8_t length[8];
    for (int i = 0; i < 8; ++i)
      length[7 - i] = static_cast<uint8_t>(bits >> (8 * i));
    update(length, 8);
    std::ostringstream text;
    text << std::hex << std::setfill('0');
    for (auto v : h)
      text << std::setw(8) << v;
    return text.str();
  }
};
} // namespace
std::string sha256(const std::vector<uint8_t> &bytes) {
  Sha s;
  s.update(bytes.data(), bytes.size());
  return s.finish();
}
std::string fileSha256(const Path &p) {
  std::ifstream f(p, std::ios::binary);
  if (!f)
    throw std::runtime_error("cannot hash: " + pathUtf8(p));
  Sha s;
  std::array<uint8_t, 65536> b{};
  while (f) {
    f.read(reinterpret_cast<char *>(b.data()), b.size());
    s.update(b.data(), static_cast<size_t>(f.gcount()));
  }
  if (!f.eof())
    throw std::runtime_error("file hash read failed");
  return s.finish();
}
} // namespace pipeline
