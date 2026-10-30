// RK3576J / AFH03 deployment program for the V3 unified 3-class ping-pong detector.
//
//   ./rknn_v3_detect --model v3_int8.rknn --input frame.raw --width 1920 --height 1080
//   ./rknn_v3_detect --model v3_int8.rknn --input frames\ --bench 500
//
// Contract (identical to the Python tool and the ONNX model):
//   * input is GRAY8; it is replicated to 3 identical channels, letterboxed to 960 with pad 114
//   * RKNN config uses mean=0 scale=255, so no manual normalisation is needed here
//   * class ids are FIXED: 0=ball, 1=hand, 2=racket
//   * output boxes are in ORIGINAL image pixels; both xyxy and xywh (top-left origin) are printed
//
// Build: see CMakeLists.txt / build.sh (needs the board's librknnrt.so + rknn_api.h)

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
constexpr int kMaxDet = 60;
constexpr float kConf[kClasses] = {0.20f, 0.25f, 0.25f};  // ball / hand / racket
constexpr float kNmsIou = 0.50f;
constexpr uint8_t kPad = 114;
const char *kNames[kClasses] = {"ball", "hand", "racket"};

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
  img->w = w;
  img->h = h;
  img->gray.resize(static_cast<size_t>(w) * h);
  const size_t n = std::fread(img->gray.data(), 1, img->gray.size(), f);
  std::fclose(f);
  return n == img->gray.size();
}

// PGM P5 reader so the tool is usable without any imaging dependency.
bool read_pgm(const std::string &path, Image *img) {
  FILE *f = std::fopen(path.c_str(), "rb");
  if (!f) return false;
  char magic[3] = {0};
  if (std::fscanf(f, "%2s", magic) != 1 || std::strcmp(magic, "P5") != 0) {
    std::fclose(f);
    return false;
  }
  int w = 0, h = 0, maxv = 0;
  if (std::fscanf(f, "%d %d %d", &w, &h, &maxv) != 3) {
    std::fclose(f);
    return false;
  }
  std::fgetc(f);  // single whitespace before the raster
  img->w = w;
  img->h = h;
  img->gray.resize(static_cast<size_t>(w) * h);
  const size_t n = std::fread(img->gray.data(), 1, img->gray.size(), f);
  std::fclose(f);
  return n == img->gray.size();
}

// Matches the Python / ONNX letterbox: bilinear resize + 114 padding.
// Bilinear (not nearest) on purpose - the model was trained with cv2.INTER_LINEAR, and nearest
// neighbour measurably shifts small-ball boxes. On the board you may hand the resize to RGA.
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
    // half-pixel centres, same convention as cv2.resize
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
  *scale = s;
  *pad_x = px;
  *pad_y = py;
}

float iou(const Det &a, const Det &b) {
  const float iw = std::max(0.0f, std::min(a.x2, b.x2) - std::max(a.x1, b.x1));
  const float ih = std::max(0.0f, std::min(a.y2, b.y2) - std::max(a.y1, b.y1));
  const float inter = iw * ih;
  if (inter <= 0.0f) return 0.0f;
  const float ua = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
  return ua > 0.0f ? inter / ua : 0.0f;
}

// out: [1, 7, N] (4 box + 3 class scores, already sigmoided inside the graph)
void decode(const float *out, int n_anchors, int img_w, int img_h, float scale, int pad_x,
            int pad_y, std::vector<Det> *dets) {
  dets->clear();
  for (int c = 0; c < kClasses; ++c) {
    std::vector<Det> cand;
    for (int a = 0; a < n_anchors; ++a) {
      float best = 0.0f;
      int best_c = -1;
      for (int k = 0; k < kClasses; ++k) {
        const float v = out[(4 + k) * n_anchors + a];
        if (v > best) {
          best = v;
          best_c = k;
        }
      }
      if (best_c != c || best < kConf[c]) continue;
      const float cx = out[0 * n_anchors + a];
      const float cy = out[1 * n_anchors + a];
      const float bw = out[2 * n_anchors + a];
      const float bh = out[3 * n_anchors + a];
      Det d;
      d.cls = c;
      d.score = best;
      d.x1 = std::max(0.0f, std::min(static_cast<float>(img_w), (cx - bw / 2 - pad_x) / scale));
      d.y1 = std::max(0.0f, std::min(static_cast<float>(img_h), (cy - bh / 2 - pad_y) / scale));
      d.x2 = std::max(0.0f, std::min(static_cast<float>(img_w), (cx + bw / 2 - pad_x) / scale));
      d.y2 = std::max(0.0f, std::min(static_cast<float>(img_h), (cy + bh / 2 - pad_y) / scale));
      if (d.x2 - d.x1 >= 1.0f && d.y2 - d.y1 >= 1.0f) cand.push_back(d);
    }
    std::sort(cand.begin(), cand.end(), [](const Det &a, const Det &b) { return a.score > b.score; });
    std::vector<Det> kept;
    for (const Det &d : cand) {
      bool dup = false;
      for (const Det &k : kept) {
        if (iou(d, k) > kNmsIou) {
          dup = true;
          break;
        }
      }
      if (!dup) kept.push_back(d);
      if (static_cast<int>(kept.size()) >= kMaxDet) break;
    }
    dets->insert(dets->end(), kept.begin(), kept.end());
  }
  std::sort(dets->begin(), dets->end(), [](const Det &a, const Det &b) { return a.score > b.score; });
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
  const size_t i = static_cast<size_t>(p * (v.size() - 1));
  return v[i];
}

}  // namespace

int main(int argc, char **argv) {
  std::string model_path, input, core_mask = "auto";
  int width = 1920, height = 1080, bench = 0;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    auto next = [&](std::string *dst) { if (i + 1 < argc) *dst = argv[++i]; };
    if (a == "--model") next(&model_path);
    else if (a == "--input") next(&input);
    else if (a == "--core-mask") next(&core_mask);
    else if (a == "--width") width = std::atoi(argv[++i]);
    else if (a == "--height") height = std::atoi(argv[++i]);
    else if (a == "--bench") bench = std::atoi(argv[++i]);
  }
  if (model_path.empty() || input.empty()) {
    std::fprintf(stderr, "usage: %s --model m.rknn --input frame.(raw|pgm) [--width W --height H] "
                         "[--bench N] [--core-mask auto|0|1|0_1]\n", argv[0]);
    return 2;
  }

  // ---- init ----
  FILE *f = std::fopen(model_path.c_str(), "rb");
  if (!f) {
    std::fprintf(stderr, "cannot open model %s\n", model_path.c_str());
    return 3;
  }
  std::fseek(f, 0, SEEK_END);
  const long sz = std::ftell(f);
  std::fseek(f, 0, SEEK_SET);
  std::vector<unsigned char> blob(static_cast<size_t>(sz));
  if (std::fread(blob.data(), 1, blob.size(), f) != blob.size()) {
    std::fclose(f);
    return 3;
  }
  std::fclose(f);

  rknn_context ctx = 0;
  int ret = rknn_init(&ctx, blob.data(), static_cast<uint32_t>(blob.size()), 0, nullptr);
  if (ret != RKNN_SUCC) {
    std::fprintf(stderr, "rknn_init failed: %d\n", ret);
    return 4;
  }
  rknn_input_output_num io_num{};
  rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
  std::printf("model=%s inputs=%u outputs=%u\n", model_path.c_str(), io_num.n_input, io_num.n_output);

  rknn_tensor_attr in_attr{};
  in_attr.index = 0;
  rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &in_attr, sizeof(in_attr));
  const int in_h = static_cast<int>(in_attr.dims[1]);
  const int in_w = static_cast<int>(in_attr.dims[2]);
  std::printf("input %dx%d fmt=%d type=%d\n", in_w, in_h, in_attr.fmt, in_attr.type);

  // dual-core scheduling (RK3576 exposes CORE_0 / CORE_1 / CORE_0_1 on recent runtimes)
  rknn_core_mask mask = RKNN_NPU_CORE_AUTO;
  if (core_mask == "0") mask = RKNN_NPU_CORE_0;
  else if (core_mask == "1") mask = RKNN_NPU_CORE_1;
  else if (core_mask == "0_1" || core_mask == "all") mask = RKNN_NPU_CORE_0_1;
  ret = rknn_set_core_mask(ctx, mask);
  std::printf("core_mask=%s -> %d\n", core_mask.c_str(), ret);

  // ---- load one frame ----
  Image img;
  const bool ok = (input.size() > 4 && input.substr(input.size() - 4) == ".pgm")
                      ? read_pgm(input, &img)
                      : read_raw(input, width, height, &img);
  if (!ok) {
    std::fprintf(stderr, "cannot read %s (%dx%d expected for raw)\n", input.c_str(), width, height);
    rknn_destroy(ctx);
    return 5;
  }

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
    rknn_output outputs[1]{};
    outputs[0].want_float = 1;
    if (rknn_outputs_get(ctx, 1, outputs, nullptr) != RKNN_SUCC) return false;
    auto t2 = std::chrono::steady_clock::now();

    const float *ptr = static_cast<const float *>(outputs[0].buf);
    const size_t total = outputs[0].size / sizeof(float);
    const int n_anchors = static_cast<int>(total / (4 + kClasses));
    decode(ptr, n_anchors, img.w, img.h, scale, pad_x, pad_y, dets);
    rknn_outputs_release(ctx, 1, outputs);
    auto t3 = std::chrono::steady_clock::now();

    *t_pre = std::chrono::duration<double, std::milli>(t1 - t0).count();
    *t_npu = std::chrono::duration<double, std::milli>(t2 - t1).count();
    *t_post = std::chrono::duration<double, std::milli>(t3 - t2).count();
    return true;
  };

  std::vector<Det> dets;
  double p = 0, n = 0, q = 0;
  for (int i = 0; i < 3; ++i) {  // warmup
    if (!run_once(&dets, &p, &n, &q)) {
      std::fprintf(stderr, "inference failed\n");
      rknn_destroy(ctx);
      return 6;
    }
  }
  if (!run_once(&dets, &p, &n, &q)) {
    rknn_destroy(ctx);
    return 6;
  }
  print_json(input, img, dets);

  if (bench > 0) {
    std::vector<double> pre, npu, post, tot;
    for (int i = 0; i < bench; ++i) {
      if (!run_once(&dets, &p, &n, &q)) break;
      pre.push_back(p);
      npu.push_back(n);
      post.push_back(q);
      tot.push_back(p + n + q);
    }
    const double mean = std::accumulate(tot.begin(), tot.end(), 0.0) / tot.size();
    std::printf("{\"frames\":%zu,\"pre_ms\":%.2f,\"npu_ms\":%.2f,\"post_ms\":%.2f,"
                "\"total_mean_ms\":%.2f,\"total_p50_ms\":%.2f,\"total_p95_ms\":%.2f,\"fps\":%.2f}\n",
                tot.size(), std::accumulate(pre.begin(), pre.end(), 0.0) / pre.size(),
                std::accumulate(npu.begin(), npu.end(), 0.0) / npu.size(),
                std::accumulate(post.begin(), post.end(), 0.0) / post.size(), mean,
                percentile(tot, 0.50), percentile(tot, 0.95), 1000.0 / mean);
  }
  rknn_destroy(ctx);
  return 0;
}
