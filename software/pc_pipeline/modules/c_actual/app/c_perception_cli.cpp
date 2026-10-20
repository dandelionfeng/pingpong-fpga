// c_perception_cli - captain-facing command line demo for the C perception engine.
//
// The CLI accepts a COLOUR image or video for convenience, but it converts to
// GRAY8 FIRST, exactly like the OV9281 chain, and every model only ever sees the
// gray3 derived from that GRAY8. Nothing downstream can silently use colour.

#include <c_perception_engine.hpp>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shellapi.h>
#endif

#include <chrono>
#include <filesystem>
#include <system_error>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Options {
  std::string image;
  std::string video;
  std::string ball_model;
  std::string hand_model;
  std::string racket_model;
  std::string unified_model;
  std::string config;
  std::string output;
  std::string overlay;
  int max_frames = 0;
  bool self_test = false;
  bool print_hashes = true;

  float base_conf = 0.02f;
  float hand_conf = 0.25f;
  float racket_conf = 0.30f;
  bool use_cuda = false;
  bool verbose = false;
};

void usage() {
  std::cout <<
      "c_perception_cli - C module gray3 perception demo (ball / hand / racket)\n"
      "\n"
      "Usage (unified 3-class model - recommended, ONE YOLO pass for hand+racket):\n"
      "  c_perception_cli --video serve.mp4 --ball-model models\\balltrack_tracknetv3.onnx \\\n"
      "      --unified-model models\\pingpong_yolov8n_gray_3cls_960.onnx --output result.jsonl\n"
      "\n"
      "Usage (legacy two-detector mode - unchanged V2.3 behaviour):\n"
      "  c_perception_cli --video serve.mp4 --ball-model models\\balltrack_tracknetv3.onnx \\\n"
      "      --hand-model models\\hand_yolov8n_gray_final_v3_960.onnx \\\n"
      "      --racket-model models\\racket_yolov8n_gray.onnx --output result.jsonl\n"
      "  c_perception_cli --image frame.png --ball-model ... --hand-model ... --racket-model ...\n"
      "\n"
      "Options:\n"
      "  --image <path>        Run a single image (colour or gray; converted to GRAY8 first)\n"
      "  --video <path>        Run a video frame by frame\n"
      "  --ball-model <path>   BallTrack TrackNetV3 ONNX (required)\n"
      "  --unified-model <path> One 3-class ONNX (0=ball,1=hand,2=racket); when set it replaces\n"
      "                        --hand-model/--racket-model and runs a single inference pass\n"
      "  --hand-model <path>   Hand YOLOv8n ONNX, 1 class (required without --unified-model)\n"
      "  --racket-model <path> Racket YOLO ONNX (required without --unified-model)\n"
      "  --config <path>       inference.yaml (optional; defaults are used if omitted)\n"
      "  --output <path>       Write one JSON object per line (.jsonl)\n"
      "  --overlay <path>      Write an annotated .mp4 (video mode)\n"
      "  --hand-conf <f>       Hand acceptance threshold (default 0.25)\n"
      "  --racket-conf <f>     Racket acceptance threshold (default 0.30)\n"
      "  --base-conf <f>       Detector inference floor (default 0.02)\n"
      "  --max-frames <n>      Stop after n frames (0 = all)\n"
      "  --cuda                Try the CUDA provider (CPU always works without it)\n"
      "  --self-test           Load models and print their hashes/IO shapes, then exit\n"
      "  --verbose             Print per-frame summaries\n"
      "  --no-hashes           Do not print model hashes\n"
      "  --help                This text\n";
}

std::string jsonEscape(const std::string &text) {
  std::string out;
  out.reserve(text.size() + 8);
  for (char c : text) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (static_cast<unsigned char>(c) < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof(buf), "\\u%04x", c);
          out += buf;
        } else {
          out += c;
        }
    }
  }
  return out;
}

std::string boxJson(const c_actual::Box &box) {
  std::ostringstream os;
  os.setf(std::ios::fixed);
  os.precision(3);
  os << "{\"class\":\"" << jsonEscape(box.class_name) << "\",\"confidence\":" << box.confidence
     << ",\"bbox\":[" << box.x << "," << box.y << "," << box.w << "," << box.h << "]}";
  return os.str();
}

std::string resultJson(const c_actual::PerceptionResult &r) {
  std::ostringstream os;
  os.setf(std::ios::fixed);
  os.precision(3);
  os << "{\"frame_id\":" << r.meta.frame_id
     << ",\"timestamp\":" << r.meta.timestamp
     << ",\"width\":" << r.width
     << ",\"height\":" << r.height
     << ",\"ball\":{\"state\":\"" << c_actual::to_string(r.ball.state) << "\""
     << ",\"detected\":" << (r.ball.detected ? "true" : "false")
     << ",\"confidence\":" << r.ball.confidence
     << ",\"center\":[" << r.ball.center.x << "," << r.ball.center.y << "]";
  if (r.ball.has_region) {
    os << ",\"region\":[" << r.ball.region.x << "," << r.ball.region.y << ","
       << r.ball.region.width << "," << r.ball.region.height << "]"
       << ",\"bbox_semantics\":\"" << r.ball.bbox_semantics << "\"";
  } else {
    os << ",\"region\":null,\"bbox_semantics\":\"none\"";
  }
  os << "},\"hands\":[";
  for (size_t i = 0; i < r.hands.size(); ++i) {
    if (i) os << ",";
    os << boxJson(r.hands[i]);
  }
  os << "],\"rackets\":[";
  for (size_t i = 0; i < r.rackets.size(); ++i) {
    if (i) os << ",";
    os << boxJson(r.rackets[i]);
  }
  os << "],\"infer_ms\":" << r.infer_ms
     << ",\"model_versions\":{\"ball\":\"" << jsonEscape(r.ball_model)
     << "\",\"hand\":\"" << jsonEscape(r.hand_model)
     << "\",\"racket\":\"" << jsonEscape(r.racket_model) << "\"";
  if (!r.unified_model.empty()) {
    os << ",\"unified\":\"" << jsonEscape(r.unified_model) << "\"";
  }
  os << "}";
  if (!r.warnings.empty()) {
    os << ",\"warnings\":[";
    for (size_t i = 0; i < r.warnings.size(); ++i) {
      if (i) os << ",";
      os << "\"" << jsonEscape(r.warnings[i]) << "\"";
    }
    os << "]";
  }
  os << "}";
  return os.str();
}

void drawOverlay(cv::Mat &canvas, const c_actual::PerceptionResult &r) {
  cv::Mat color;
  cv::cvtColor(canvas, color, cv::COLOR_GRAY2BGR);
  color.copyTo(canvas);

  for (const auto &box : r.hands) {
    cv::rectangle(canvas, cv::Rect(static_cast<int>(box.x), static_cast<int>(box.y),
                                   static_cast<int>(box.w), static_cast<int>(box.h)),
                  cv::Scalar(0, 200, 255), 2);
    cv::putText(canvas, "hand " + cv::format("%.2f", box.confidence),
                cv::Point(static_cast<int>(box.x), static_cast<int>(box.y) - 6),
                cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 200, 255), 2);
  }
  for (const auto &box : r.rackets) {
    cv::rectangle(canvas, cv::Rect(static_cast<int>(box.x), static_cast<int>(box.y),
                                   static_cast<int>(box.w), static_cast<int>(box.h)),
                  cv::Scalar(0, 255, 0), 2);
    cv::putText(canvas, "racket " + cv::format("%.2f", box.confidence),
                cv::Point(static_cast<int>(box.x), static_cast<int>(box.y) - 6),
                cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 255, 0), 2);
  }
  if (r.ball.detected) {
    const cv::Point center(static_cast<int>(r.ball.center.x), static_cast<int>(r.ball.center.y));
    cv::circle(canvas, center, 6, cv::Scalar(60, 60, 255), -1);
    cv::putText(canvas, "ball " + cv::format("%.2f", r.ball.confidence),
                center + cv::Point(10, -10), cv::FONT_HERSHEY_SIMPLEX, 0.6,
                cv::Scalar(60, 60, 255), 2);
    if (r.ball.has_region) {
      cv::rectangle(canvas,
                    cv::Rect(static_cast<int>(r.ball.region.x), static_cast<int>(r.ball.region.y),
                             static_cast<int>(r.ball.region.width),
                             static_cast<int>(r.ball.region.height)),
                    cv::Scalar(200, 200, 200), 1);
    }
  }
  cv::putText(canvas, std::string("ball=") + c_actual::to_string(r.ball.state),
              cv::Point(12, 28), cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(255, 255, 255), 2);
}

bool parseArgs(int argc, char **argv, Options *opt, std::string *error) {
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto next = [&](std::string *out) -> bool {
      if (i + 1 >= argc) {
        *error = "missing value for " + arg;
        return false;
      }
      *out = argv[++i];
      return true;
    };
    if (arg == "--help" || arg == "-h") {
      usage();
      std::exit(0);
    } else if (arg == "--image") {
      if (!next(&opt->image)) return false;
    } else if (arg == "--video") {
      if (!next(&opt->video)) return false;
    } else if (arg == "--ball-model") {
      if (!next(&opt->ball_model)) return false;
    } else if (arg == "--unified-model") {
      if (!next(&opt->unified_model)) return false;
    } else if (arg == "--hand-model") {
      if (!next(&opt->hand_model)) return false;
    } else if (arg == "--racket-model") {
      if (!next(&opt->racket_model)) return false;
    } else if (arg == "--config") {
      if (!next(&opt->config)) return false;
    } else if (arg == "--output") {
      if (!next(&opt->output)) return false;
    } else if (arg == "--overlay") {
      if (!next(&opt->overlay)) return false;
    } else if (arg == "--max-frames") {
      std::string v;
      if (!next(&v)) return false;
      opt->max_frames = std::stoi(v);
    } else if (arg == "--hand-conf") {
      std::string v;
      if (!next(&v)) return false;
      opt->hand_conf = std::stof(v);
    } else if (arg == "--racket-conf") {
      std::string v;
      if (!next(&v)) return false;
      opt->racket_conf = std::stof(v);
    } else if (arg == "--base-conf") {
      std::string v;
      if (!next(&v)) return false;
      opt->base_conf = std::stof(v);
    } else if (arg == "--cuda") {
      opt->use_cuda = true;
    } else if (arg == "--self-test") {
      opt->self_test = true;
    } else if (arg == "--verbose") {
      opt->verbose = true;
    } else if (arg == "--no-hashes") {
      opt->print_hashes = false;
    } else {
      *error = "unknown argument: " + arg;
      return false;
    }
  }
  if (opt->image.empty() && opt->video.empty()) {
    *error = "either --image or --video is required";
    return false;
  }
  if (opt->ball_model.empty()) {
    *error = "MISSING_MODEL: --ball-model is required";
    return false;
  }
  if (opt->unified_model.empty() && (opt->hand_model.empty() || opt->racket_model.empty())) {
    *error = "MISSING_MODEL: pass --unified-model, or both --hand-model and --racket-model";
    return false;
  }
  return true;
}

// Small YAML subset reader for inference.yaml (key: value, nested by indent).
std::string yamlLookup(const std::string &text, const std::string &section,
                       const std::string &key) {
  std::istringstream stream(text);
  std::string line;
  bool in_section = section.empty();
  while (std::getline(stream, line)) {
    const auto hash = line.find('#');
    if (hash != std::string::npos) line = line.substr(0, hash);
    if (line.empty()) continue;
    const bool indented = (line[0] == ' ' || line[0] == '\t');
    std::string trimmed = line;
    const auto first = trimmed.find_first_not_of(" \t");
    if (first == std::string::npos) continue;
    trimmed = trimmed.substr(first);
    const auto colon = trimmed.find(':');
    if (colon == std::string::npos) continue;
    const std::string name = trimmed.substr(0, colon);
    const std::string value = trimmed.substr(colon + 1);
    if (!indented && !section.empty()) {
      in_section = (name == section);
      continue;
    }
    if (in_section && name == key) {
      std::string v = value;
      const auto b = v.find_first_not_of(" \t");
      v = (b == std::string::npos) ? "" : v.substr(b);
      const auto e = v.find_last_not_of(" \t\r");
      if (e != std::string::npos) v = v.substr(0, e + 1);
      return v;
    }
  }
  return "";
}

}  // namespace

#ifdef _WIN32
namespace {
// MSVC hands `main` an ANSI (code-page) command line, which destroys non-ASCII
// arguments such as a Chinese folder name before our code ever sees them. Read
// the UTF-16 command line instead and convert each argument to UTF-8.
std::string wideToUtf8(const wchar_t *text) {
  if (!text) return std::string();
  const int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
  if (size <= 0) return std::string();
  std::string out(static_cast<size_t>(size - 1), '\0');
  WideCharToMultiByte(CP_UTF8, 0, text, -1, out.data(), size, nullptr, nullptr);
  return out;
}

// UTF-8 -> UTF-16, for APIs that need a wide path on Windows.
std::wstring utf8Path(const std::string &text) {
  if (text.empty()) return std::wstring();
  const int size = MultiByteToWideChar(CP_UTF8, 0, text.c_str(),
                                       static_cast<int>(text.size()), nullptr, 0);
  if (size <= 0) return std::wstring(text.begin(), text.end());
  std::wstring out(static_cast<size_t>(size), L'\0');
  MultiByteToWideChar(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()),
                      out.data(), size);
  return out;
}

// std::ofstream interprets a narrow path using the ANSI code page on Windows,
// so a Chinese path silently fails to open. Open via std::filesystem::path.
void openOutput(std::ofstream &stream, const std::string &utf8_path) {
  stream.open(std::filesystem::path(utf8Path(utf8_path)),
              std::ios::out | std::ios::trunc);
}

std::vector<std::string> utf8Args() {
  int argc_w = 0;
  LPWSTR *argv_w = CommandLineToArgvW(GetCommandLineW(), &argc_w);
  std::vector<std::string> args;
  if (!argv_w) return args;
  args.reserve(static_cast<size_t>(argc_w));
  for (int i = 0; i < argc_w; ++i) args.push_back(wideToUtf8(argv_w[i]));
  LocalFree(argv_w);
  return args;
}
}  // namespace
#endif

namespace {
// std::ifstream's narrow constructor interprets the path with the ANSI code page
// on Windows, so a UTF-8 path containing non-ASCII characters silently fails to
// open. cv::imread has the same limitation; this is the byte-decoding fallback.
void openInput(std::ifstream &stream, const std::string &utf8_path) {
#ifdef _WIN32
  stream.open(std::filesystem::path(utf8Path(utf8_path)), std::ios::binary);
#else
  stream.open(utf8_path, std::ios::binary);
#endif
}
}  // namespace

int main(int argc, char **argv) {
#ifdef _WIN32
  // Render non-ASCII output correctly in the console too.
  SetConsoleOutputCP(CP_UTF8);
  std::vector<std::string> arg_storage = utf8Args();
  std::vector<char *> arg_ptrs;
  if (!arg_storage.empty()) {
    arg_ptrs.reserve(arg_storage.size());
    for (auto &s : arg_storage) arg_ptrs.push_back(s.data());
    argc = static_cast<int>(arg_ptrs.size());
    argv = arg_ptrs.data();
  }
#endif
  Options opt;
  std::string error;
  if (!parseArgs(argc, argv, &opt, &error)) {
    std::cerr << "ERROR: " << error << "\n\n";
    usage();
    return 2;
  }

  if (!opt.config.empty()) {
    std::ifstream in(opt.config);
    if (in) {
      std::stringstream buffer;
      buffer << in.rdbuf();
      const std::string text = buffer.str();
      auto apply = [&](const std::string &section, const std::string &key, float *target) {
        const std::string v = yamlLookup(text, section, key);
        if (!v.empty()) {
          try {
            *target = std::stof(v);
          } catch (...) {
          }
        }
      };
      apply("detector_common", "base_conf", &opt.base_conf);
      apply("racket", "racket_conf", &opt.racket_conf);
      apply("hand", "hand_conf", &opt.hand_conf);
    }
  }

  c_actual::ModelPaths paths;
  paths.ball_track = opt.ball_model;
  paths.hand = opt.hand_model;
  paths.racket = opt.racket_model;
  paths.unified = opt.unified_model;

  c_actual::Config config;
  config.base_conf = opt.base_conf;
  config.hand_conf = opt.hand_conf;
  config.racket_conf = opt.racket_conf;
  config.use_cuda = opt.use_cuda;
  config.verbose = opt.verbose;

  c_actual::CPerceptionEngine engine;
  if (!engine.load(paths, config, &error)) {
    std::cerr << "ERROR: " << error << "\n";
    std::cerr << "Hint: pass --ball-model plus either --unified-model, or both "
                 "--hand-model and --racket-model, with existing .onnx files.\n";
    return 3;
  }

  std::cout << "C perception engine ready\n";
  std::cout << "  " << engine.versionString() << "\n";
  std::cout << "  ball   : " << paths.ball_track << "\n";
  if (engine.usingUnifiedDetector()) {
    std::cout << "  unified: " << paths.unified << "  (ONE pass -> hand + racket; 960 class order "
                 "ball=0 hand=1 racket=2)\n";
    std::cout << "  note   : the unified model's ball class is NOT emitted; "
                 "BallTrack stays the only ball source\n";
    if (!paths.hand.empty() || !paths.racket.empty()) {
      std::cout << "  ignored: " << paths.hand << " / " << paths.racket << "\n";
    }
  } else {
    std::cout << "  hand   : " << paths.hand << "\n";
    std::cout << "  racket : " << paths.racket << "\n";
  }
  std::cout << "  base_conf=" << opt.base_conf << " hand_conf=" << opt.hand_conf
            << " racket_conf=" << opt.racket_conf << "\n";
  std::cout << "  input  : GRAY8 (CV_8UC1); gray3 conversion and all preprocessing are internal\n";

  if (opt.self_test) {
    std::cout << "\nSELF-TEST OK: all required models loaded"
              << (engine.usingUnifiedDetector() ? " (unified 3-class)" : " (hand + racket)")
              << ".\n";
    return 0;
  }

  std::ofstream out;
  if (!opt.output.empty()) {
    // Create the parent directory so a path like out\result.jsonl works on a
    // clean checkout instead of failing to open.
    const size_t slash = opt.output.find_last_of("\\/");
    if (slash != std::string::npos && slash > 0) {
      std::error_code ec;
      std::filesystem::create_directories(opt.output.substr(0, slash), ec);
    }
    openOutput(out, opt.output);
    if (!out) {
      std::cerr << "ERROR: cannot write --output " << opt.output << "\n";
      return 4;
    }
  }

  auto emit = [&](const c_actual::PerceptionResult &r) {
    const std::string line = resultJson(r);
    if (out) out << line << "\n";
    if (opt.verbose) std::cout << line << "\n";
  };

  if (!opt.image.empty()) {
    cv::Mat loaded = cv::imread(opt.image, cv::IMREAD_UNCHANGED);
    if (loaded.empty()) {
      // Windows non-ASCII paths: OpenCV's imread goes through the ANSI code page,
      // so fall back to opening the bytes ourselves with a wide path.
      std::ifstream in;
      openInput(in, opt.image);
      if (!in) {
        std::cerr << "ERROR: cannot read image " << opt.image << "\n";
        return 5;
      }
      std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(in)),
                                       std::istreambuf_iterator<char>());
      loaded = cv::imdecode(bytes, cv::IMREAD_UNCHANGED);
    }
    if (loaded.empty()) {
      std::cerr << "ERROR: cannot decode image " << opt.image << "\n";
      return 5;
    }
    cv::Mat gray;
    if (loaded.channels() == 3) {
      cv::cvtColor(loaded, gray, cv::COLOR_BGR2GRAY);
    } else if (loaded.channels() == 4) {
      cv::cvtColor(loaded, gray, cv::COLOR_BGRA2GRAY);
    } else {
      gray = loaded;
    }
    c_actual::FrameMeta meta;
    meta.frame_id = 0;
    const auto result = engine.inferGray(gray, meta);
    emit(result);
    std::cout << "\n" << resultJson(result) << "\n";
    if (!opt.overlay.empty()) {
      cv::Mat canvas = gray.clone();
      drawOverlay(canvas, result);
      cv::imwrite(opt.overlay, canvas);
      std::cout << "overlay written: " << opt.overlay << "\n";
    }
    std::cout << "\nDone. frames=1\n";
    return 0;
  }

  cv::VideoCapture capture(opt.video);
  if (!capture.isOpened()) {
    std::cerr << "ERROR: cannot open video " << opt.video << "\n";
    return 6;
  }
  const double fps = capture.get(cv::CAP_PROP_FPS) > 1.0 ? capture.get(cv::CAP_PROP_FPS) : 60.0;
  cv::VideoWriter writer;
  cv::Size writer_size;

  int frames = 0;
  double total_ms = 0.0;
  int64_t detected_ball = 0, warmup = 0, dropout = 0;
  size_t total_hands = 0, total_rackets = 0;

  while (true) {
    cv::Mat frame;
    if (!capture.read(frame) || frame.empty()) break;
    cv::Mat gray;
    if (frame.channels() == 3) {
      cv::cvtColor(frame, gray, cv::COLOR_BGR2GRAY);
    } else if (frame.channels() == 4) {
      cv::cvtColor(frame, gray, cv::COLOR_BGRA2GRAY);
    } else {
      gray = frame;
    }
    c_actual::FrameMeta meta;
    meta.frame_id = static_cast<uint64_t>(frames);
    meta.timestamp = frames / fps;
    const auto result = engine.inferGray(gray, meta);
    emit(result);

    total_ms += result.infer_ms;
    if (result.ball.state == c_actual::BallState::kDetected) ++detected_ball;
    else if (result.ball.state == c_actual::BallState::kWarmup) ++warmup;
    else if (result.ball.state == c_actual::BallState::kDropout) ++dropout;
    total_hands += result.hands.size();
    total_rackets += result.rackets.size();

    if (!opt.overlay.empty()) {
      cv::Mat canvas = gray.clone();
      drawOverlay(canvas, result);
      if (!writer.isOpened()) {
        writer_size = canvas.size();
        writer.open(opt.overlay, cv::VideoWriter::fourcc('m', 'p', '4', 'v'), fps, writer_size);
      }
      if (writer.isOpened() && canvas.size() == writer_size) writer.write(canvas);
    }

    ++frames;
    if (opt.max_frames > 0 && frames >= opt.max_frames) break;
  }
  capture.release();
  if (writer.isOpened()) writer.release();

  std::cout << "\nDone. frames=" << frames
            << "  ball DETECTED=" << detected_ball
            << " WARMUP=" << warmup
            << " DROPOUT=" << dropout
            << "  hand boxes=" << total_hands
            << "  racket boxes=" << total_rackets << "\n";
  if (frames > 0) {
    std::cout << "mean inference " << (total_ms / frames) << " ms/frame\n";
  }
  if (!opt.output.empty()) std::cout << "jsonl: " << opt.output << "\n";
  if (!opt.overlay.empty()) std::cout << "overlay: " << opt.overlay << "\n";
  return 0;
}
