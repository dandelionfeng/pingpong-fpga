// RK3576J / AFH03 - V3 3-class detector with a **class filter** (ball + hand only).
//
//   ./rknn_v3_detect_filtered --model v3_960_fp16_dfl_layout.rknn \
//        --input frame.raw --width 1920 --height 1080
//   ./rknn_v3_detect_filtered --model ... --input frame.raw --classes 0,1 --bench 500 --core-mask 0_1
//
// The network is UNCHANGED: it still emits 3 classes from the same weights. This program simply
// drops the classes listed in --drop (default: racket) AFTER decoding and NMS, so the result
// handed to downstream modules only ever contains ball and hand. Nothing is retrained, nothing in
// the ONNX/RKNN is modified, and ball/hand detections are bit-identical to the unfiltered run.
//
// Output layout is the DFL one (see the AFH03 package): `dfl` [1,64,18900] + `scores_logits`
// [1,3,18900]. Decode: softmax over 16 bins -> expectation -> dist2bbox with grid-centre anchors.
//
// Contract: GRAY8 -> 3 identical channels -> letterbox 960 pad 114 -> RKNN (mean 0/scale 255 in
// config, so no extra division here). Boxes in ORIGINAL pixels; xyxy and xywh (top-left origin,
// matching the C module DetectionResult).

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <numeric>
#include <string>
#include <vector>

#include "rknn_api.h"

namespace {

constexpr int kClasses = 3;          // the model still has 3; we filter afterwards
constexpr int kRegMax = 16;
constexpr int kMaxDet = 60;
constexpr float kConf[kClasses] = {0.20f, 0.25f, 0.25f};
constexpr float kNmsIou = 0.50f;
constexpr uint8_t kPad = 114;
const char *kNames[kClasses] = {"ball", "hand", "racket"};
constexpr int kGrids[3] = {120, 60, 30};
constexpr int kStrides[3] = {8, 16, 32};

struct Det {
  int cls;
  float score;
  float x1, y1, x2, y2;
};

struct Image {
  int w = 0, h = 0;
  std::vector<uint8_t> gray;
};

bool read_raw(const std::string &path, int w, int h, Image *img) {
  FILE *f = std::fopen(path.c_str(), "rb");
  if (!f) return false;
  img->w = w; img->h = h;
  img->gray.resize(static_cast<size_t>(w) * h);
  const size_t n = std::fread(img->gray.data(), 1, img->gray.size(), f);
  std::fclose(f);
  return n == img->gray.size();
}

bool read_pgm(const std::string &path, Image *img) {
  FILE *f = std::fopen(path.c_str(), "rb");
  if (!f) return false;
  char magic[3] = {0};
  if (std::fscanf(f, "%2s", magic) != 1 || std::strcmp(magic, "P5") != 0) { std::fclose(f); return false; }
  int w = 0, h = 0, maxv = 0;
  if (std::fscanf(f, "%d %d %d", &w, &h, &maxv) != 3) { std::fclose(f); return false; }
  std::fgetc(f);
  img->w = w; img->h = h;
  img->gray.resize(static_cast<size_t>(w) * h);
  const size_t n = std::fread(img->gray.data(), 1, img->gray.size(), f);
  std::fclose(f);
  return n == img->gray.size();
}

void letterbox_gray3(const Image &img, int size, std::vector<uint8_t> *nhwc, float *scale,
                     int *pad_x, int *pad_y) {
  const float s = std::min(static_cast<float>(size) / img.w, static_cast<float>(size) / img.h);
  const int nw = std::max(1, static_cast<int>(std::lround(img.w * s)));
  const int nh = std::max(1, static_cast<int>(std::lround(img.h * s)));
  const int px = (size - nw) / 2;
  const int py = (size - nh) / 2;
  nhwc->assign(static_cast<size_t>(size) * size * 3, kPad);
  const float fx = static_cast<float>(img.w) / nw;
  const float fy = static_cast<float>(img.h) / nh;
  for (int y = 0; y < nh; ++y) {
    const float sy = (y + 0.5f) * fy - 0.5f;
    int y0 = static_cast<int>(std::floor(sy));
    const float wy = sy - y0;
    int y1 = y0 + 1;
    if (y0 < 0) y0 = 0;
    if (y1 > img.h - 1) y1 = img.h - 1;
    if (y0 > img.h - 1) y0 = img.h - 1;
    for (int x = 0; x < nw; ++x) {
      const float sx = (x + 0.5f) * fx - 0.5f;
      int x0 = static_cast<int>(std::floor(sx));
      const float wx = sx - x0;
      int x1 = x0 + 1;
      if (x0 < 0) x0 = 0;
      if (x1 > img.w - 1) x1 = img.w - 1;
      if (x0 > img.w - 1) x0 = img.w - 1;
      const float p00 = img.gray[static_cast<size_t>(y0) * img.w + x0];
      const float p01 = img.gray[static_cast<size_t>(y0) * img.w + x1];
      const float p10 = img.gray[static_cast<size_t>(y1) * img.w + x0];
      const float p11 = img.gray[static_cast<size_t>(y1) * img.w + x1];
      const float top = p00 + (p01 - p00) * wx;
      const float bot = p10 + (p11 - p10) * wx;
      const uint8_t v = static_cast<uint8_t>(std::lround(top + (bot - top) * wy));
      const size_t o = static_cast<size_t>(py + y) * size * 3 + static_cast<size_t>(px + x) * 3;
      (*nhwc)[o + 0] = v;
      (*nhwc)[o + 1] = v;
      (*nhwc)[o + 2] = v;
    }
  }
  *scale = s; *pad_x = px; *pad_y = py;
}

float iou(const Det &a, const Det &b) {
  const float iw = std::max(0.0f, std::min(a.x2, b.x2) - std::max(a.x1, b.x1));
  const float ih = std::max(0.0f, std::min(a.y2, b.y2) - std::max(a.y1, b.y1));
  const float inter = iw * ih;
  if (inter <= 0.0f) return 0.0f;
  const float ua = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
  return ua > 0.0f ? inter / ua : 0.0f;
}

void decode_dfl(const float *dfl, const float *logits, int n_anchors, int img_w, int img_h,
                float scale, int pad_x, int pad_y, std::vector<Det> per_class[kClasses]) {
  const int per_grid[3] = {kGrids[0] * kGrids[0], kGrids[1] * kGrids[1], kGrids[2] * kGrids[2]};
  int offset = 0;
  for (int level = 0; level < 3; ++level) {
    const int g = kGrids[level];
    const int count = per_grid[level];
    const int stride = kStrides[level];
    for (int a = 0; a < count; ++a) {
      const int idx = offset + a;
      float best = 0.0f;
      int best_c = -1;
      for (int c = 0; c < kClasses; ++c) {
        const float v = 1.0f / (1.0f + std::exp(-logits[c * n_anchors + idx]));
        if (v > best) { best = v; best_c = c; }
      }
      if (best_c < 0 || best < kConf[best_c]) continue;
      float dist[4] = {0.0f, 0.0f, 0.0f, 0.0f};
      for (int side = 0; side < 4; ++side) {
        float mx = -1e30f;
        for (int b = 0; b < kRegMax; ++b) {
          const float v = dfl[(side * kRegMax + b) * n_anchors + idx];
          if (v > mx) mx = v;
        }
        float sum = 0.0f, acc = 0.0f;
        for (int b = 0; b < kRegMax; ++b) {
          const float e = std::exp(dfl[(side * kRegMax + b) * n_anchors + idx] - mx);
          sum += e;
          acc += e * static_cast<float>(b);
        }
        dist[side] = sum > 0.0f ? acc / sum : 0.0f;
      }
      const float cx = (static_cast<float>(a % g) + 0.5f) * stride;
      const float cy = (static_cast<float>(a / g) + 0.5f) * stride;
      Det d;
      d.cls = best_c;
      d.score = best;
      d.x1 = std::max(0.0f, std::min(static_cast<float>(img_w), (cx - dist[0] * stride - pad_x) / scale));
      d.y1 = std::max(0.0f, std::min(static_cast<float>(img_h), (cy - dist[1] * stride - pad_y) / scale));
      d.x2 = std::max(0.0f, std::min(static_cast<float>(img_w), (cx + dist[2] * stride - pad_x) / scale));
      d.y2 = std::max(0.0f, std::min(static_cast<float>(img_h), (cy + dist[3] * stride - pad_y) / scale));
      per_class[d.cls].push_back(d);
    }
    offset += count;
  }
}

void nms_into(std::vector<Det> *out, std::vector<Det> *cand) {
  std::sort(cand->begin(), cand->end(), [](const Det &a, const Det &b) { return a.score > b.score; });
  std::vector<Det> kept;
  for (const Det &d : *cand) {
    bool dup = false;
    for (const Det &k : kept) { if (iou(d, k) > kNmsIou) { dup = true; break; } }
    if (!dup) kept.push_back(d);
    if (static_cast<int>(kept.size()) >= kMaxDet) break;
  }
  out->insert(out->end(), kept.begin(), kept.end());
}

void print_json(const std::string &path, const Image &img, const std::vector<Det> &dets,
                int filtered_out) {
  std::printf("{\"image\":\"%s\",\"image_width\":%d,\"image_height\":%d,\"filtered_out\":%d,"
              "\"detections\":[", path.c_str(), img.w, img.h, filtered_out);
  for (size_t i = 0; i < dets.size(); ++i) {
    const Det &d = dets[i];
    std::printf("%s{\"class_id\":%d,\"class_name\":\"%s\",\"confidence\":%.4f,"
                "\"bbox_xyxy\":[%.2f,%.2f,%.2f,%.2f],\"bbox_xywh\":[%.2f,%.2f,%.2f,%.2f]}",
                i ? "," : "", d.cls, kNames[d.cls], d.score, d.x1, d.y1, d.x2, d.y2,
                d.x1, d.y1, d.x2 - d.x1, d.y2 - d.y1);
  }
  std::printf("]}\n");
}

double percentile(std::vector<double> v, double p) {
  if (v.empty()) return 0.0;
  std::sort(v.begin(), v.end());
  return v[static_cast<size_t>(p * (v.size() - 1))];
}

}  // namespace

int main(int argc, char **argv) {
  std::string model_path, input, core_mask = "auto", classes = "0,1";
  int width = 1920, height = 1080, bench = 0;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    auto next = [&](std::string *dst) { if (i + 1 < argc) *dst = argv[++i]; };
    if (a == "--model") next(&model_path);
    else if (a == "--input") next(&input);
    else if (a == "--core-mask") next(&core_mask);
    else if (a == "--classes") next(&classes);
    else if (a == "--width") width = std::atoi(argv[++i]);
    else if (a == "--height") height = std::atoi(argv[++i]);
    else if (a == "--bench") bench = std::atoi(argv[++i]);
  }
  if (model_path.empty() || input.empty()) {
    std::fprintf(stderr, "usage: %s --model m.rknn --input frame.(raw|pgm) [--width W --height H]\n"
                         "          [--classes 0,1] [--bench N] [--core-mask auto|0|1|0_1]\n", argv[0]);
    return 2;
  }

  // parse the keep-list (default: ball + hand -> racket is dropped)
  bool keep[kClasses] = {false, false, false};
  {
    std::string cur;
    for (char ch : classes + ",") {
      if (ch == ',' || ch == ' ') {
        if (!cur.empty()) {
          const int c = std::atoi(cur.c_str());
          if (c >= 0 && c < kClasses) keep[c] = true;
          cur.clear();
        }
      } else {
        cur.push_back(ch);
      }
    }
  }
  std::printf("class filter: keep=[%s%s%s]  (model still emits 3 classes)\n",
              keep[0] ? "ball " : "", keep[1] ? "hand " : "", keep[2] ? "racket " : "");

  FILE *f = std::fopen(model_path.c_str(), "rb");
  if (!f) { std::fprintf(stderr, "cannot open model %s\n", model_path.c_str()); return 3; }
  std::fseek(f, 0, SEEK_END);
  const long sz = std::ftell(f);
  std::fseek(f, 0, SEEK_SET);
  std::vector<unsigned char> blob(static_cast<size_t>(sz));
  if (std::fread(blob.data(), 1, blob.size(), f) != blob.size()) { std::fclose(f); return 3; }
  std::fclose(f);

  rknn_context ctx = 0;
  int ret = rknn_init(&ctx, blob.data(), static_cast<uint32_t>(blob.size()), 0, nullptr);
  if (ret != RKNN_SUCC) { std::fprintf(stderr, "rknn_init failed: %d\n", ret); return 4; }

  rknn_input_output_num io_num{};
  rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
  int idx_dfl = -1, idx_logits = -1;
  for (uint32_t i = 0; i < io_num.n_output; ++i) {
    rknn_tensor_attr at{};
    at.index = i;
    if (rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &at, sizeof(at)) != RKNN_SUCC) continue;
    const int ch = static_cast<int>(at.dims[1]);
    std::printf("  out[%u] %-24s dims=[%d,%d,%d] type=%d qnt=%d\n", i, at.name, at.dims[0],
                at.dims[1], at.dims[2], at.type, static_cast<int>(at.qnt_type));
    if (ch == 64 && idx_dfl < 0) idx_dfl = static_cast<int>(i);
    else if (ch == kClasses && idx_logits < 0) idx_logits = static_cast<int>(i);
  }
  if (idx_dfl < 0 || idx_logits < 0) {
    std::fprintf(stderr, "need a 64-channel and a 3-channel output\n");
    rknn_destroy(ctx);
    return 5;
  }

  rknn_tensor_attr in_attr{};
  in_attr.index = 0;
  rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &in_attr, sizeof(in_attr));
  const int in_h = static_cast<int>(in_attr.dims[1]);
  const int in_w = static_cast<int>(in_attr.dims[2]);

#ifndef NO_CORE_MASK
  rknn_core_mask mask = RKNN_NPU_CORE_AUTO;
  if (core_mask == "0") mask = RKNN_NPU_CORE_0;
  else if (core_mask == "1") mask = RKNN_NPU_CORE_1;
  else if (core_mask == "0_1" || core_mask == "all") mask = RKNN_NPU_CORE_0_1;
  ret = rknn_set_core_mask(ctx, mask);
  std::printf("core_mask=%s -> ret=%d\n", core_mask.c_str(), ret);
#else
  std::printf("core_mask: compiled out; runtime AUTO\n");
#endif

  Image img;
  const bool ok = (input.size() > 4 && input.substr(input.size() - 4) == ".pgm")
                      ? read_pgm(input, &img) : read_raw(input, width, height, &img);
  if (!ok) { std::fprintf(stderr, "cannot read %s\n", input.c_str()); rknn_destroy(ctx); return 6; }

  std::vector<uint8_t> nhwc;
  float scale = 1.0f;
  int pad_x = 0, pad_y = 0;

  auto run_once = [&](std::vector<Det> *out, int *filtered_out, double *t_pre, double *t_npu,
                      double *t_post) {
    auto t0 = std::chrono::steady_clock::now();
    letterbox_gray3(img, in_w, &nhwc, &scale, &pad_x, &pad_y);
    auto t1 = std::chrono::steady_clock::now();

    rknn_input inputs[1]{};
    inputs[0].index = 0;
    inputs[0].type = RKNN_TENSOR_UINT8;
    inputs[0].fmt = RKNN_TENSOR_NHWC;
    inputs[0].size = static_cast<uint32_t>(nhwc.size());
    inputs[0].buf = nhwc.data();
    if (rknn_inputs_set(ctx, 1, inputs) != RKNN_SUCC) return false;
    if (rknn_run(ctx, nullptr) != RKNN_SUCC) return false;
    std::vector<rknn_output> outputs(io_num.n_output);
    for (uint32_t i = 0; i < io_num.n_output; ++i) {
      outputs[i].index = i;
      outputs[i].want_float = 1;
      outputs[i].is_prealloc = 0;
    }
    if (rknn_outputs_get(ctx, io_num.n_output, outputs.data(), nullptr) != RKNN_SUCC) return false;
    auto t2 = std::chrono::steady_clock::now();

    // ---- decode all 3 classes, then FILTER (filter happens after decoding, as required) ----
    const float *dfl = static_cast<const float *>(outputs[idx_dfl].buf);
    const float *logits = static_cast<const float *>(outputs[idx_logits].buf);
    const int n = static_cast<int>(outputs[idx_dfl].size / sizeof(float) / (4 * kRegMax));
    std::vector<Det> per_class[kClasses];
    decode_dfl(dfl, logits, n, img.w, img.h, scale, pad_x, pad_y, per_class);

    out->clear();
    int dropped = 0;
    for (int c = 0; c < kClasses; ++c) {
      if (!keep[c]) { dropped += static_cast<int>(per_class[c].size()); continue; }  // filter here
      nms_into(out, &per_class[c]);
    }
    std::sort(out->begin(), out->end(), [](const Det &a, const Det &b) { return a.score > b.score; });
    *filtered_out = dropped;

    rknn_outputs_release(ctx, io_num.n_output, outputs.data());
    auto t3 = std::chrono::steady_clock::now();
    *t_pre = std::chrono::duration<double, std::milli>(t1 - t0).count();
    *t_npu = std::chrono::duration<double, std::milli>(t2 - t1).count();
    *t_post = std::chrono::duration<double, std::milli>(t3 - t2).count();
    return true;
  };

  std::vector<Det> dets;
  int dropped = 0;
  double p = 0, n = 0, q = 0;
  for (int i = 0; i < 3; ++i) {
    if (!run_once(&dets, &dropped, &p, &n, &q)) { rknn_destroy(ctx); return 7; }
  }
  if (!run_once(&dets, &dropped, &p, &n, &q)) { rknn_destroy(ctx); return 7; }
  print_json(input, img, dets, dropped);

  if (bench > 0) {
    std::vector<double> pre, npu, post, tot;
    for (int i = 0; i < bench; ++i) {
      if (!run_once(&dets, &dropped, &p, &n, &q)) break;
      pre.push_back(p); npu.push_back(n); post.push_back(q); tot.push_back(p + n + q);
    }
    const double mean = std::accumulate(tot.begin(), tot.end(), 0.0) / tot.size();
    std::printf("{\"frames\":%zu,\"pre_ms\":%.2f,\"npu_ms\":%.2f,\"post_ms\":%.2f,"
                "\"total_mean_ms\":%.2f,\"total_p50_ms\":%.2f,\"total_p95_ms\":%.2f,\"fps\":%.2f}\n",
                tot.size(), std::accumulate(pre.begin(), pre.end(), 0.0) / pre.size(),
                std::accumulate(npu.begin(), npu.end(), 0.0) / npu.size(),
                std::accumulate(post.begin(), post.end(), 0.0) / post.size(),
                mean, percentile(tot, 0.50), percentile(tot, 0.95), 1000.0 / mean);
  }
  rknn_destroy(ctx);
  return 0;
}
