#include "pipeline/pipeline.hpp"
#include "pipeline/stereo.hpp"
#include <csignal>
#include <iostream>
#include <map>
#ifdef _WIN32
// clang-format off
#include <windows.h>
#include <shellapi.h>
// clang-format on
#endif
using namespace pipeline;
namespace {
std::atomic<bool> *cancellation = nullptr;
void cancel(int) {
  if (cancellation)
    cancellation->store(true);
}
} // namespace
int main(int argc, char **argv) {
  std::vector<std::string> args;
#ifdef _WIN32
  int n = 0;
  auto wide = CommandLineToArgvW(GetCommandLineW(), &n);
  for (int i = 0; i < n; ++i) {
    int bytes = WideCharToMultiByte(CP_UTF8, 0, wide[i], -1, nullptr, 0,
                                    nullptr, nullptr);
    std::string value(static_cast<size_t>(bytes), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide[i], -1, value.data(), bytes, nullptr,
                        nullptr);
    value.pop_back();
    args.push_back(value);
  }
  LocalFree(wide);
  SetConsoleOutputCP(CP_UTF8);
#else
  for (int i = 0; i < argc; ++i)
    args.emplace_back(argv[i]);
#endif
  try {
    std::map<std::string, std::string> options;
    std::set<std::string> flags;
    for (size_t i = 1; i < args.size(); ++i) {
      auto key = args[i];
      if (key == "--full" || key == "--realtime" || key == "--no-images" ||
          key == "--no-stages" || key == "--help" || key == "--detect-right") {
        flags.insert(key);
        continue;
      }
      if (key.rfind("--", 0) != 0 || i + 1 >= args.size())
        throw std::runtime_error("expected --option value");
      static const std::set<std::string> known = {
          "--input",         "--output",
          "--motion",        "--detector",
          "--replay",        "--import-export",
          "--manifest",      "--repeat",
          "--timeout-ms",    "--detector-rate",
          "--mock-delay-ms", "--detector-delay-ms",
          "--model-config",  "--detector-timeout-ms",
          "--config",        "--import-video", "--measurement-calibration"};
      if (!known.count(key))
        throw std::runtime_error("unknown option: " + key);
      options[key] = args[++i];
    }
    if (flags.count("--help") || args.size() == 1) {
      std::cout << "A USB stereo pipeline " << PIPELINE_VERSION
                << "\n  --import-export DIR "
                   "--manifest OUTPUT.json\n  --input MANIFEST --output "
                   "NEW_DIR [--motion cpu|mock-dma|pcie] [--detector "
                   "none|replay|recorded|model|module-test] [--replay JSON_OR_JSONL] [--full] "
                   "[--realtime] "
                   "[--no-images] [--no-stages] [--repeat N] [--config JSON] "
                   "[--measurement-calibration JSON]\n";
      return 0;
    }
    if (options.count("--import-video")) {
      if (!options.count("--manifest"))
        throw std::runtime_error("--manifest required");
      auto j = importStereoAvi(utf8Path(options["--import-video"]),
                               utf8Path(options["--manifest"]));
      std::cout << j.at("provenance").dump(2) << '\n';
      return 0;
    }
    if (options.count("--import-export")) {
      if (!options.count("--manifest"))
        throw std::runtime_error("--manifest required");
      auto j = importExportPackage(utf8Path(options["--import-export"]),
                                   utf8Path(options["--manifest"]));
      std::cout << Json{{"status", "imported"},
                        {"pairs", j["frames"].size()},
                        {"manifest", options["--manifest"]}}
                       .dump(2)
                << '\n';
      return 0;
    }
    if (!options.count("--input") || !options.count("--output"))
      throw std::runtime_error("--input and --output required");
    RunConfig c;
    c.cancellation = std::make_shared<std::atomic<bool>>(false);
    cancellation = c.cancellation.get();
    std::signal(SIGINT, cancel);
    c.full = flags.count("--full") != 0;
    c.realtime = flags.count("--realtime") != 0;
    c.save_images = !flags.count("--no-images");
    c.save_stages = !flags.count("--no-stages");
    c.detect_right = flags.count("--detect-right") != 0;
    auto val = [&](const char *k, const std::string &d) {
      return options.count(k) ? options[k] : d;
    };
    c.motion = val("--motion", "cpu");
    c.detector = val("--detector", "none");
    c.replay = utf8Path(val("--replay", ""));
    c.repeat = std::stoull(val("--repeat", "1"));
    c.timeout_ms = std::stoi(val("--timeout-ms", "500"));
    c.detector_timeout_ms = std::stoi(val("--detector-timeout-ms", "0"));
    c.detector_config = utf8Path(val("--model-config", ""));
    c.measurement_calibration = utf8Path(val("--measurement-calibration", ""));
    c.detector_rate = std::stoi(val("--detector-rate", "25"));
    c.mock_delay_ms = std::stoi(val("--mock-delay-ms", "0"));
    c.detector_delay_ms = std::stoi(val("--detector-delay-ms", "0"));
    if (options.count("--config")) {
      auto j = Json::parse(readText(utf8Path(options["--config"])));
      if (j.at("schema_version") != 1)
        throw std::runtime_error("config schema mismatch");
      c.algorithm.version = j.at("config_version");
      c.algorithm.threshold = j.value("threshold", 12);
      c.timeout_ms = j.value("timeout_ms", c.timeout_ms);
      c.detector_rate = j.value("detector_rate", c.detector_rate);
      if (j.contains("queues")) {
        auto &q = j["queues"];
        c.input_queue = q.value("input", c.input_queue);
        c.detection_queue = q.value("detection", c.detection_queue);
        c.completion_queue = q.value("completion", c.completion_queue);
        c.motion_queue = q.value("motion", c.motion_queue);
      }
      if (c.algorithm.threshold < 0 || c.algorithm.threshold > 255)
        throw std::runtime_error("threshold must be 0..255");
    }
    auto summary = runPipeline(utf8Path(options["--input"]),
                               utf8Path(options["--output"]), c);
    cancellation = nullptr;
    std::cout << summary.dump(2) << '\n';
    return summary["status"] == "passed" ? 0 : 2;
  } catch (const std::exception &e) {
    cancellation = nullptr;
    std::cerr << Json{{"status", "failed"}, {"error", e.what()}}.dump() << '\n';
    return 1;
  }
}
