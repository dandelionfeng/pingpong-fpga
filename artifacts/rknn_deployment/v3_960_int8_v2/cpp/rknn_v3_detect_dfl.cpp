// RK3576J / AFH03 C++ inference for the V3 3-class ping-pong detector - DFL layout.
//
//   ./rknn_v3_detect --model v3_int8.rknn --input frame.raw --width 1920 --height 1080
//   ./rknn_v3_detect --model v3_int8.rknn --input frames_dir --bench 500 --core-mask 0_1
//
// Two output layouts are supported, chosen with --layout:
//
//   dfl    (recommended, RKNN-friendly):  model outputs `dfl` [1,64,18900] (16 bins x 4 sides)
//          and `scores_logits` [1,3,18900] (pre-sigmoid). This file runs the DFL decode itself:
//          softmax over the 16 bins -> expectation -> distances -> dist2bbox, then sigmoid.
//          These tensors are NOT shared with the concat, so RKNN can INT8-quantise them properly.
//
//   split  : model outputs `boxes` [1,4,18900] (already pixel-space xyxy) and `scores`
//          [1,3,18900] (sigmoid). No DFL needed. NOTE: measured worse in INT8 because `scores`
//          is a concat input and inherits its coarse quantisation scale.
//
// Contract (unchanged): GRAY8 -> 3 identical channels -> letterbox 960 pad 114 -> RKNN
// (mean 0 / scale 255 in config, so do NOT divide again here). Class ids are FIXED:
// 0=ball, 1=hand, 2=racket. Boxes are returned in ORIGINAL image pixels, xyxy and xywh
// (top-left origin, matching the C module).

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <numeric>
#include <string>
#include <vector>

#include "rknn_api.h"

namespace {

constexpr int kClasses = 3;
constexpr int kRegMax = 16;              // DFL bins
constexpr int kMaxDet = 60;
constexpr float kConf[kClasses] = {0.20f, 0.25f, 0.25f};
constexpr float kNmsIou = 0.50f;
constexpr uint8_t kPad = 114;
const char *kNames[kClasses] = {"ball", "hand", "racket"};
constexpr int kGrids[3] = {120, 60, 30};      // P3/P4/P5 at 960
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

// Bilinear letterbox (matches cv2.INTER_LINEAR used in training, half-pixel centres).
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

void push_nms(std::vector<Det> *out, std::vector<Det> *cand) {
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

// ---- layout "dfl": dfl [64,N] logits + class logits [3,N] --------------------------------
// DFL: for each of the 4 sides, softmax over the 16 bins and take the expectation.
// Anchors: grid centres (i+0.5)*stride, matching ultralytics make_anchors(grid, stride, 0.5).
void decode_dfl(const float *dfl, const float *logits, int n_anchors, int img_w, int img_h,
                float scale, int pad_x, int pad_y, std::vector<Det> *dets) {
  const int per_grid[3] = {kGrids[0] * kGrids[0], kGrids[1] * kGrids[1], kGrids[2] * kGrids[2]};
  int offset = 0;
  for (int level = 0; level < 3; ++level) {
    const int g = kGrids[level];
    const int count = per_grid[level];
    const int stride = kStrides[level];
    for (int a = 0; a < count; ++a) {
      const int idx = offset + a;
      // class scores
      float best = 0.0f;
      int best_c = -1;
      for (int c = 0; c < kClasses; ++c) {
        const float v = 1.0f / (1.0f + std::exp(-logits[c * n_anchors + idx]));
        if (v > best) { best = v; best_c = c; }
      }
      if (best_c < 0 || best < kConf[best_c]) continue;
      // DFL expectation for the 4 sides (layout: side-major, 16 bins each)
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
      dets[d.cls].push_back(d);
    }
    offset += count;
  }
}

// ---- layout "split": boxes [4,N] pixel xyxy + scores [3,N] -------------------------------
void decode_split(const float *boxes, const float *scores, int n_anchors, int img_w, int img_h,
                  float scale, int pad_x, int pad_y, std::vector<Det> *dets) {
  for (int a = 0; a < n_anchors; ++a) {
    float best = 0.0f;
    int best_c = -1;
    for (int c = 0; c < kClasses; ++c) {
      const float v = scores[c * n_anchors + a];
      if (v > best) { best = v; best_c = c; }
    }
    if (best_c < 0 || best < kConf[best_c]) continue;
    Det d;
    d.cls = best_c;
    d.score = best;
    d.x1 = std::max(0.0f, std::min(static_cast<float>(img_w), (boxes[0 * n_anchors + a] - pad_x) / scale));
    d.y1 = std::max(0.0f, std::min(static_cast<float>(img_h), (boxes[1 * n_anchors + a] - pad_y) / scale));
    d.x2 = std::max(0.0f, std::min(static_cast<float>(img_w), (boxes[2 * n_anchors + a] - pad_x) / scale));
    d.y2 = std::max(0.0f, std::min(static_cast<float>(img_h), (boxes[3 * n_anchors + a] - pad_y) / scale));
    dets[d.cls].push_back(d);
  }
}

void print_json(const std::string &path, const Image &img, const std::vector<Det> &dets) {
  std::printf("{\"image\":\"%s\",\"image_width\":%d,\"image_height\":%d,\"detections\":[",
              path.c_str(), img.w, img.h);
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
  std::string model_path, input, core_mask = "auto", layout = "dfl";
  int width = 1920, height = 1080, bench = 0;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    auto next = [&](std::string *dst) { if (i + 1 < argc) *dst = argv[++i]; };
    if (a == "--model") next(&model_path);
    else if (a == "--input") next(&input);
    else if (a == "--core-mask") next(&core_mask);
    else if (a == "--layout") next(&layout);
    else if (a == "--width") width = std::atoi(argv[++i]);
    else if (a == "--height") height = std::atoi(argv[++i]);
    else if (a == "--bench") bench = std::atoi(argv[++i]);
  }
  if (model_path.empty() || input.empty()) {
    std::fprintf(stderr, "usage: %s --model m.rknn --input frame.(raw|pgm) [--width W --height H]\n"
                         "          [--layout dfl|split] [--bench N] [--core-mask auto|0|1|0_1]\n", argv[0]);
    return 2;
  }

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
  std::printf("model=%s inputs=%u outputs=%u layout=%s\n", model_path.c_str(), io_num.n_input,
              io_num.n_output, layout.c_str());

  // Locate the outputs we need by their shapes: dfl [64,N] / scores_logits [3,N] /
  // boxes [4,N] / scores [3,N]. Never index by position - the graph has 6..8 outputs.
  int idx_dfl = -1, idx_logits = -1, idx_boxes = -1, idx_scores = -1;
  for (uint32_t i = 0; i < io_num.n_output; ++i) {
    rknn_tensor_attr at{};
    at.index = i;
    if (rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &at, sizeof(at)) != RKNN_SUCC) continue;
    const int ch = static_cast<int>(at.dims[1]);
    std::printf("  out[%u] %-28s dims=[%d,%d,%d] type=%d qnt=%d\n", i, at.name, at.dims[0],
                at.dims[1], at.dims[2], at.type, static_cast<int>(at.qnt_type));
    if (ch == 64 * 4 / 4 * 1 && ch == 64 && idx_dfl < 0) idx_dfl = static_cast<int>(i);
    else if (ch == 4 && idx_boxes < 0) idx_boxes = static_cast<int>(i);
    else if (ch == 3) { if (idx_logits < 0) idx_logits = static_cast<int>(i); }
  }
  const bool use_dfl = (layout == "dfl");
  if (use_dfl && (idx_dfl < 0 || idx_logits < 0)) {
    std::fprintf(stderr, "layout=dfl needs a 64-channel and a 3-channel output\n");
    rknn_destroy(ctx);
    return 5;
  }
  if (!use_dfl && (idx_boxes < 0 || idx_scores < 0)) {
    std::fprintf(stderr, "layout=split needs a 4-channel and a 3-channel output\n");
    rknn_destroy(ctx);
    return 5;
  }

  rknn_tensor_attr in_attr{};
  in_attr.index = 0;
  rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &in_attr, sizeof(in_attr));
  const int in_h = static_cast<int>(in_attr.dims[1]);
  const int in_w = static_cast<int>(in_attr.dims[2]);
  std::printf("input %dx%d fmt=%d type=%d\n", in_w, in_h, in_attr.fmt, in_attr.type);

#ifndef NO_CORE_MASK
  rknn_core_mask mask = RKNN_NPU_CORE_AUTO;
  if (core_mask == "0") mask = RKNN_NPU_CORE_0;
  else if (core_mask == "1") mask = RKNN_NPU_CORE_1;
  else if (core_mask == "0_1" || core_mask == "all") mask = RKNN_NPU_CORE_0_1;
  ret = rknn_set_core_mask(ctx, mask);
  std::printf("core_mask=%s -> ret=%d (0 means ok)\n", core_mask.c_str(), ret);
#else
  std::printf("core_mask: compiled out (-DNO_CORE_MASK); runtime uses AUTO\n");
#endif

  Image img;
  const bool ok = (input.size() > 4 && input.substr(input.size() - 4) == ".pgm")
                      ? read_pgm(input, &img) : read_raw(input, width, height, &img);
  if (!ok) { std::fprintf(stderr, "cannot read %s\n", input.c_str()); rknn_destroy(ctx); return 6; }

  std::vector<uint8_t> nhwc;
  float scale = 1.0f;
  int pad_x = 0, pad_y = 0;

  auto run_once = [&](std::vector<Det> *dets, double *t_pre, double *t_npu, double *t_post) {
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

    std::vector<Det> per_class[kClasses];
    if (use_dfl) {
      const float *dfl = static_cast<const float *>(outputs[idx_dfl].buf);
      const float *logits = static_cast<const float *>(outputs[idx_logits].buf);
      const int n = static_cast<int>(outputs[idx_dfl].size / sizeof(float) / (4 * kRegMax));
      decode_dfl(dfl, logits, n, img.w, img.h, scale, pad_x, pad_y, per_class);
    } else {
      const float *boxes = static_cast<const float *>(outputs[idx_boxes].buf);
      const float *scores = static_cast<const float *>(outputs[idx_scores].buf);
      const int n = static_cast<int>(outputs[idx_boxes].size / sizeof(float) / 4);
      decode_split(boxes, scores, n, img.w, img.h, scale, pad_x, pad_y, per_class);
    }
    dets->clear();
    for (int c = 0; c < kClasses; ++c) push_nms(dets, &per_class[c]);
    std::sort(dets->begin(), dets->end(), [](const Det &a, const Det &b) { return a.score > b.score; });
    rknn_outputs_release(ctx, io_num.n_output, outputs.data());
    auto t3 = std::chrono::steady_clock::now();

    *t_pre = std::chrono::duration<double, std::milli>(t1 - t0).count();
    *t_npu = std::chrono::duration<double, std::milli>(t2 - t1).count();
    *t_post = std::chrono::duration<double, std::milli>(t3 - t2).count();
    return true;
  };

  std::vector<Det> dets;
  double p = 0, n = 0, q = 0;
  for (int i = 0; i < 3; ++i) {
    if (!run_once(&dets, &p, &n, &q)) { std::fprintf(stderr, "inference failed\n"); rknn_destroy(ctx); return 7; }
  }
  if (!run_once(&dets, &p, &n, &q)) { rknn_destroy(ctx); return 7; }
  print_json(input, img, dets);

  if (bench > 0) {
    std::vector<double> pre, npu, post, tot;
    for (int i = 0; i < bench; ++i) {
      if (!run_once(&dets, &p, &n, &q)) break;
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
