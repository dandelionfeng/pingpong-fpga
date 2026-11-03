#pragma once
// Host-only syntax stub for compiling the ARM Neon source on x86. It is not
// linked into production and must never be shipped as a functional backend.
#include <cmath>
#include <cstdint>
#include <cstring>

typedef uint16_t __fp16;

struct int8x8_t { int8_t val[8]; };
struct uint8x8_t { uint8_t val[8]; };
struct int8x8x3_t { int8x8_t val[3]; };
struct uint8x8x3_t { uint8x8_t val[3]; };
struct float16x4_t { uint16_t val[4]; };
struct float16x4x3_t { float16x4_t val[3]; };
struct float32x4_t { float val[4]; };
struct int32x4_t { int32_t val[4]; };
struct int16x4_t { int16_t val[4]; };
struct int16x8_t { int16_t val[8]; };

inline float32x4_t vld1q_f32(const float *p) {
  float32x4_t r; for (int i = 0; i < 4; ++i) r.val[i] = p[i]; return r;
}
inline float32x4_t vdupq_n_f32(float v) { float32x4_t r; for (int i=0;i<4;++i) r.val[i]=v; return r; }
inline int32x4_t vdupq_n_s32(int v) { int32x4_t r; for (int i=0;i<4;++i) r.val[i]=v; return r; }
inline float32x4_t vmulq_n_f32(float32x4_t a, float b) { for (int i=0;i<4;++i) a.val[i]*=b; return a; }
inline float32x4_t vaddq_f32(float32x4_t a, float32x4_t b) { for (int i=0;i<4;++i) a.val[i]+=b.val[i]; return a; }
inline int32x4_t vcvtq_s32_f32(float32x4_t a) { int32x4_t r; for (int i=0;i<4;++i) r.val[i]=(int32_t)lroundf(a.val[i]); return r; }
inline int32x4_t vaddq_s32(int32x4_t a, int32x4_t b) { for (int i=0;i<4;++i) a.val[i]+=b.val[i]; return a; }
inline int16x4_t vqmovn_s32(int32x4_t a) { int16x4_t r; for (int i=0;i<4;++i) r.val[i]=(int16_t)std::max(-32768,std::min(32767,a.val[i])); return r; }
inline int16x8_t vcombine_s16(int16x4_t a, int16x4_t b) { int16x8_t r; for(int i=0;i<4;++i){r.val[i]=a.val[i];r.val[i+4]=b.val[i];} return r; }
inline int8x8_t vqmovn_s16(int16x8_t a) { int8x8_t r; for (int i=0;i<8;++i) r.val[i]=(int8_t)std::max(-128,std::min(127,(int)a.val[i])); return r; }
inline void vst1_s8(int8_t *p, int8x8_t a) { for (int i=0;i<8;++i) p[i]=a.val[i]; }
inline uint8x8_t vdup_n_u8(uint8_t v) { uint8x8_t r; for(int i=0;i<8;++i)r.val[i]=v; return r; }
inline uint8x8_t veor_u8(uint8x8_t a, uint8x8_t b) { for(int i=0;i<8;++i)a.val[i]^=b.val[i]; return a; }
inline uint8x8x3_t vld3_u8(const uint8_t *p) { uint8x8x3_t r; for(int i=0;i<8;++i)for(int c=0;c<3;++c)r.val[c].val[i]=p[3*i+c]; return r; }
inline void vst3_u8(uint8_t *p, uint8x8x3_t a) { for(int i=0;i<8;++i)for(int c=0;c<3;++c)p[3*i+c]=a.val[c].val[i]; }
inline void vst3_s8(int8_t *p, int8x8x3_t a) { for(int i=0;i<8;++i)for(int c=0;c<3;++c)p[3*i+c]=a.val[c].val[i]; }
inline float16x4_t vcvt_f16_f32(float32x4_t a) { float16x4_t r; for(int i=0;i<4;++i)r.val[i]=0; return r; }
inline void vst3_f16(__fp16 *p, float16x4x3_t a) { for(int i=0;i<4;++i)for(int c=0;c<3;++c)p[3*i+c]=a.val[c].val[i]; }
