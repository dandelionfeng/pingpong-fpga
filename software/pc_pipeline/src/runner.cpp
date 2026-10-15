#include "pipeline/pipeline.hpp"
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <opencv2/core/version.hpp>
#include <sstream>
namespace pipeline {
static std::unique_ptr<std::ostream> outputStream(const Path &p) {
  auto stream = std::make_unique<std::ofstream>(p, std::ios::binary);
  if (!*stream)
    throw std::runtime_error("cannot open output stream: " + pathUtf8(p));
  return stream;
}
RunWriter::RunWriter(Path output, Json config)
    : root_(std::move(output)), configuration_(std::move(config)) {
  if (std::filesystem::exists(root_ / "run.json") ||
      std::filesystem::exists(root_ / "frames.jsonl"))
    throw std::runtime_error(
        "output already contains a run; choose a new directory");
  std::filesystem::create_directories(root_);
  images_ = configuration_.value("save_images", true);
  stages_ = configuration_.value("save_stages", true);
  frames_ = outputStream(root_ / "frames.jsonl");
  detections_ = outputStream(root_ / "detections.jsonl");
  errors_ = outputStream(root_ / "errors.jsonl");
  csv_ = outputStream(root_ / "frames.csv");
  *csv_ << "pair_id,timestamp_ns,valid,left_reference_valid,left_reference_id,"
           "right_reference_valid,right_reference_id,measurement_status\n";
  writeText(root_ / "run.json", Json{{"schema_version", 1},
                                     {"status", "running"},
                                     {"configuration", configuration_},
                                     {"software_version", PIPELINE_VERSION},
                                     {"opencv_version", CV_VERSION}}
                                    .dump(2));
}
void RunWriter::frame(const FramePair &f, const MotionResult &motion,
                      const Json &measurement) {
  std::lock_guard<std::mutex> lock(mutex_);
  Json j = metaJson(f.meta);
  j.update(
      {{"schema_version", 1},
       {"motion_valid", motion.valid},
       {"motion_error", motion.error},
       {"motion_backend", motion.backend},
       {"task_id", motion.task_id},
       {"completion_ns", motion.completion_ns},
       {"measurement",
        measurement.is_null() ? Json{{"status", "unavailable"}} : measurement},
       {"eyes", Json::array()}});
  for (int e = 0; e < 2; ++e) {
    auto &m = motion.eyes[e];
    Json eye = {{"eye", eyeName(static_cast<Eye>(e))},
                {"reference_valid", m.reference_valid},
                {"reference_id", m.reference_id},
                {"reference_timestamp_ns", m.reference_timestamp_ns},
                {"observation_status",
                 motion.valid
                     ? (m.reference_valid ? "observed_motion_mask"
                                          : "invalid_uninitialized_reference")
                     : "invalid_processing"}};
    eye["stages_available"] = Json::array();
    for (int s = 0; s < 7; ++s)
      if (!m.stages[s].empty())
        eye["stages_available"].push_back(s);
    if (motion.valid) {
      std::vector<uint8_t> pixel(m.stages[6].data,
                                 m.stages[6].data + m.stages[6].total());
      eye["mask_sha256"] = sha256(pixel);
      eye["foreground_pixels"] = cv::countNonZero(m.stages[6]);
      if (images_) {
        std::ostringstream name;
        name << "pair_" << std::setw(8) << std::setfill('0') << f.meta.pair_id;
        auto dir = root_ / "images" / name.str() / eyeName(static_cast<Eye>(e));
        writeImage(dir / "original.png", f.original[e]);
        writeImage(dir / "search.png", f.search[e]);
        writeImage(dir / "mask.png", m.stages[6]);
        writeBytes(dir / "mask_lsb.bin", packMask(m.stages[6]));
        auto roi =
            cropRoi(f, static_cast<Eye>(e), {EyeWidth / 2., EyeHeight / 2.});
        writeImage(dir / "roi_inspection_center.png", roi.image);
        eye["inspection_roi"] = {
            {"source", "image_center_not_ball_measurement"},
            {"origin", {roi.origin.x, roi.origin.y}},
            {"valid",
             {roi.valid.x, roi.valid.y, roi.valid.width, roi.valid.height}},
            {"padding", roi.padding_value}};
        if (stages_) {
          const char *names[] = {"gaussian", "difference", "threshold",
                                 "erode1",   "dilate1",    "dilate2",
                                 "erode2"};
          for (int stage = 0; stage < 7; ++stage)
            if (!m.stages[stage].empty())
              writeImage(dir / (std::string(names[stage]) + ".png"),
                         m.stages[stage]);
        }
        eye["image_directory"] =
            pathUtf8(std::filesystem::relative(dir, root_));
      }
    }
    j["eyes"].push_back(eye);
  }
  *frames_ << j.dump() << '\n';
  *csv_ << f.meta.pair_id << ',' << f.meta.timestamp_ns << ',' << motion.valid
        << ',' << motion.eyes[0].reference_valid << ','
        << motion.eyes[0].reference_id << ',' << motion.eyes[1].reference_valid
        << ',' << motion.eyes[1].reference_id << ','
        << (measurement.is_null() ? "unavailable"
                                  : measurement.value("status", "provided"))
        << '\n';
  if (!*frames_ || !*csv_)
    throw std::runtime_error("result write failed");
  ++count_;
}
void RunWriter::detection(const DetectionResult &r) {
  std::lock_guard<std::mutex> lock(mutex_);
  Json j = metaJson(r.meta);
  j.update({{"source_pair_id", r.meta.pair_id},
            {"eye", eyeName(r.eye)},
            {"task_id", r.task_id},
            {"generation", r.generation},
            {"completed_ns", r.completed_ns},
            {"status", r.status},
            {"backend", r.backend},
            {"boxes", r.boxes}});
  j["reference_id"] = r.reference_id;
  j["reference_valid"] = r.reference_valid;
  j["reference_timestamp_ns"] = r.reference_timestamp_ns;
  *detections_ << j.dump() << '\n';
  if (!*detections_)
    throw std::runtime_error("detection write failed");
}
void RunWriter::error(const Meta &m, const std::string &layer,
                      const std::string &error, const Json &evidence) {
  std::lock_guard<std::mutex> lock(mutex_);
  auto j = metaJson(m);
  j.update({{"layer", layer}, {"error", error}, {"logged_ns", monotonicNs()}});
  if (!evidence.empty())
    j["evidence"] = evidence;
  *errors_ << j.dump() << '\n';
  if (!*errors_)
    throw std::runtime_error("error log write failed");
}
void RunWriter::finish(Json summary) {
  std::lock_guard<std::mutex> lock(mutex_);
  frames_->flush();
  detections_->flush();
  errors_->flush();
  csv_->flush();
  summary.update({{"schema_version", 1},
                  {"configuration", configuration_},
                  {"software_version", PIPELINE_VERSION},
                  {"opencv_version", CV_VERSION},
                  {"frames_written", count_}});
  writeText(root_ / "run.json", summary.dump(2));
}
Json runPipeline(const Path &manifest, const Path &output, const RunConfig &cfg,
                 std::function<void(Json)> progress) {
  if (cfg.motion != "cpu" && cfg.motion != "mock-dma" && cfg.motion != "pcie") {
    throw std::runtime_error("motion must be cpu/mock-dma/pcie");
  }
  if (!cfg.repeat || cfg.timeout_ms < 1 || cfg.detector_rate < 1 ||
      !cfg.input_queue || !cfg.detection_queue || !cfg.completion_queue ||
      !cfg.motion_queue)
    throw std::runtime_error("invalid runtime configuration");
  auto reg = moduleRegistry();
  if (cfg.full && (!reg.measurement || cfg.detector == "none"))
    throw std::runtime_error("full system unavailable: B MeasurementModule and "
                             "a detector are required");
  std::unique_ptr<DetectorBackend> detector;
  if (cfg.detector == "replay")
    detector =
        std::make_unique<ReplayDetector>(cfg.replay, cfg.detector_delay_ms);
  else if (cfg.detector == "model" || cfg.detector == "module-test") {
    if (!reg.detector)
      throw std::runtime_error(
          "actual model unavailable: build C module and provide model/version");
    detector = reg.detector();
    if (!detector ||
        (cfg.detector == "model" && detector->mode() != "actual-model"))
      throw std::runtime_error(
          "model mode requires a C backend marked actual-model");
    if (cfg.detector == "module-test" &&
        detector->mode().rfind("integration-test", 0) != 0)
      throw std::runtime_error(
          "module-test requires an integration-test backend");
  } else if (cfg.detector != "none")
    throw std::runtime_error("detector must be none/replay/model");
  auto measurement = reg.measurement ? reg.measurement() : nullptr;
  if (cfg.full && (cfg.detector != "model" || !measurement ||
                   measurement->version().rfind("integration-test", 0) == 0))
    throw std::runtime_error(
        "full system requires actual B measurement and C model; use explicit "
        "replay/module-test for integration");
  std::unique_ptr<DetectorScheduler> scheduler;
  if (detector)
    scheduler = std::make_unique<DetectorScheduler>(
        std::move(detector), cfg.detector_rate, cfg.timeout_ms,
        cfg.detection_queue, cfg.completion_queue);
  Json input = Json::parse(readText(manifest));
  bool live = input.value("mode", "file") == "v4l2";
  if (live && cfg.repeat != 1)
    throw std::runtime_error("live input cannot repeat");
  Json config = {
      {"motion", cfg.motion},
      {"detector", cfg.detector},
      {"full", cfg.full},
      {"realtime", cfg.realtime},
      {"save_images", cfg.save_images},
      {"save_stages", cfg.save_stages},
      {"threshold", cfg.algorithm.threshold},
      {"config_version", cfg.algorithm.version},
      {"input_manifest", pathUtf8(std::filesystem::absolute(manifest))},
      {"input_manifest_sha256", fileSha256(manifest)},
      {"repeat", cfg.repeat},
      {"protocol", "a-motion-v1-draft-lsb0"},
      {"timeout_ms", cfg.timeout_ms},
      {"detector_rate", cfg.detector_rate},
      {"queues",
       {{"input", cfg.input_queue},
        {"detection", cfg.detection_queue},
        {"completion", cfg.completion_queue},
        {"motion", cfg.motion_queue},
        {"display", 1},
        {"cache", 8},
        {"detector_concurrency", 1}}},
      {"detect_right", cfg.detect_right}};
  config["mock_delay_ms"] = cfg.mock_delay_ms;
  config["detector_delay_ms"] = cfg.detector_delay_ms;
  if (cfg.detector == "replay") {
    config["replay_file"] = pathUtf8(std::filesystem::absolute(cfg.replay));
    config["replay_sha256"] = fileSha256(cfg.replay);
    config["replay_provenance"] =
        Json::parse(readText(cfg.replay))
            .value("provenance", "unspecified_detection_replay");
  }
  std::unique_ptr<MotionBackend> motion;
  if (cfg.motion == "pcie") {
    if (!reg.motion)
      unavailablePcieBackend();
    motion = reg.motion(cfg.algorithm, cfg.timeout_ms, cfg.motion_queue);
    if (!motion || motion->mode() != "pcie")
      throw std::runtime_error("vendor motion factory must supply pcie mode");
  } else
    motion = std::make_unique<SoftwareMotionBackend>(
        cfg.motion == "mock-dma", cfg.algorithm, cfg.timeout_ms,
        cfg.motion_queue);
  RunWriter writer(output, config);
  if (scheduler)
    scheduler->onDiscard = [&](const DetectorContext &c) {
      writer.error(c.meta, "detector_queue",
                   "oldest pending detection replaced: eye=" + eyeName(c.eye) +
                       " task_id=" + std::to_string(c.task_id));
    };
  writeText(output / "input-manifest.json", input.dump(2));
  BoundedQueue<FrameRead> incoming(cfg.input_queue);
  FrameCache cache;
  std::atomic<uint64_t> replaced{0};
  std::exception_ptr sourceException;
  auto cancelled = [&] { return cfg.cancellation && cfg.cancellation->load(); };
  std::thread reader([&] {
    try {
      for (uint64_t repetition = 0; repetition < cfg.repeat && !cancelled();
           ++repetition) {
        std::unique_ptr<FrameSource> source;
        if (live)
          source = std::make_unique<V4l2FrameSource>(
              input.at("device"), nativeV4l2Syscalls(),
              input.value("exposure_absolute", 10),
              input.value("pixel_format", "auto"));
        else
          source = std::make_unique<FileFrameSource>(manifest);
        uint64_t maxId = 0;
        int64_t period = 0;
        uint64_t liveLimit = input.value("max_pairs", uint64_t(300));
        if (!live) {
          auto &entries = input.at("frames");
          if (!entries.empty()) {
            maxId = entries.back().at("pair_id").get<uint64_t>();
            period = entries.back().at("timestamp_ns").get<int64_t>() -
                     entries.front().at("timestamp_ns").get<int64_t>() +
                     input.value("repeat_step_ns", int64_t(16000000));
          }
        }
        auto wallStart = Clock::now();
        int64_t timeStart = 0;
        uint64_t attempts = 0;
        while (!cancelled()) {
          auto r = source->next();
          if (r.end || (live && attempts++ >= liveLimit))
            break;
          if (r.frame && repetition) {
            auto f = std::make_shared<FramePair>();
            f->meta = r.frame->meta;
            f->original = r.frame->original;
            f->search = r.frame->search;
            f->meta.pair_id += repetition * maxId;
            f->meta.timestamp_ns += static_cast<int64_t>(repetition) * period;
            for (auto &t : f->meta.eye_timestamp_ns)
              t += static_cast<int64_t>(repetition) * period;
            f->meta.source = "file-repeat";
            r.frame = f;
            r.meta = f->meta;
          }
          if (cfg.realtime && r.frame) {
            if (!timeStart)
              timeStart = r.meta.timestamp_ns;
            auto due = wallStart + std::chrono::nanoseconds(
                                       r.meta.timestamp_ns - timeStart);
            while (!cancelled() && Clock::now() < due)
              std::this_thread::sleep_for(std::chrono::milliseconds(1));
          }
          bool dropped = false;
          std::optional<FrameRead> discarded;
          if (!incoming.push(std::move(r), cfg.realtime, &dropped, &discarded))
            break;
          if (dropped) {
            ++replaced;
            writer.error(discarded->meta, "input_queue",
                         "oldest pending frame replaced; algorithm uses actual "
                         "sample dt");
          }
        }
      }
    } catch (...) {
      sourceException = std::current_exception();
    }
    incoming.close();
  });
  uint64_t processed = 0, errors = 0;
  std::string pixelHashes;
  std::vector<double> durations;
  auto start = Clock::now();
  Json summary;
  try {
    while (!cancelled()) {
      auto item = incoming.pop(std::chrono::milliseconds(10));
      if (!item) {
        if (incoming.closed())
          break;
        continue;
      }
      auto &r = *item;
      if (!r.error.empty()) {
        writer.error(r.meta, "input", r.error, r.evidence);
        ++errors;
        continue;
      }
      cache.put(r.frame);
      auto begin = Clock::now();
      motion->submit({r.meta, r.frame->search}, {cfg.mock_delay_ms, false});
      std::vector<MotionResult> results;
      while (results.empty()) {
        results = motion->poll();
        if (results.empty())
          std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
      auto &m = results.front();
      if (!m.valid) {
        writer.error(r.meta, "motion", m.error);
        ++errors;
      }
      std::vector<DetectionResult> completions;
      if (scheduler) {
        completions = scheduler->poll();
        for (auto &d : completions)
          writer.detection(d);
        if (measurement)
          measurement->acceptDetections(completions);
        scheduler->submit(*r.frame, Eye::Left, !cfg.realtime, &m);
        if (cfg.detect_right ||
            (measurement && measurement->requestRightDetection(*r.frame, m)))
          scheduler->submit(*r.frame, Eye::Right, !cfg.realtime, &m);
      }
      std::vector<DetectionResult> matching;
      for (auto &d : completions)
        if (d.meta.pair_id == r.meta.pair_id && d.status == "ok")
          matching.push_back(d);
      Json measures;
      if (measurement && m.valid) {
        measures = measurement->process(*r.frame, m, matching);
        if (measures.at("pair_id").get<uint64_t>() != r.meta.pair_id)
          throw std::runtime_error("B result source_pair_id mismatch");
      }
      writer.frame(*r.frame, m, measures);
      if (m.valid)
        for (auto &e : m.eyes)
          pixelHashes += sha256(std::vector<uint8_t>(
              e.stages[6].data, e.stages[6].data + e.stages[6].total()));
      durations.push_back(
          std::chrono::duration<double, std::milli>(Clock::now() - begin)
              .count());
      ++processed;
      if (progress)
        progress({{"processed", processed},
                  {"pair_id", r.meta.pair_id},
                  {"errors", errors}});
    }
    incoming.close();
    reader.join();
    if (sourceException)
      std::rethrow_exception(sourceException);
    if (scheduler) {
      scheduler->finish();
      while (!scheduler->statistics().at("done").get<bool>() ||
             scheduler->statistics().at("completed_pending").get<size_t>()) {
        auto list = scheduler->poll();
        for (auto &d : list)
          writer.detection(d);
        if (measurement)
          measurement->acceptDetections(list);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
    }
  } catch (const std::exception &e) {
    incoming.close();
    if (reader.joinable())
      reader.join();
    writer.error({}, "runtime", e.what());
    writer.finish(
        {{"status", "failed"}, {"processed", processed}, {"error", e.what()}});
    throw;
  }
  std::sort(durations.begin(), durations.end());
  auto percentile = [&](double p) {
    return durations.empty()
               ? 0.
               : durations[static_cast<size_t>(p * (durations.size() - 1))];
  };
  summary = {
      {"status", cancelled() ? "cancelled"
                             : (errors ? "completed_with_errors" : "passed")},
      {"processed", processed},
      {"errors", errors},
      {"input_replaced", replaced.load()},
      {"input_queue_peak", incoming.peak()},
      {"frame_cache_size", cache.size()},
      {"frame_object_peak", LiveObjects::peak_frames.load()},
      {"context_object_peak", LiveObjects::peak_contexts.load()},
      {"mask_sequence_sha256",
       sha256(std::vector<uint8_t>(pixelHashes.begin(), pixelHashes.end()))},
      {"elapsed_ms",
       std::chrono::duration<double, std::milli>(Clock::now() - start).count()},
      {"per_pair_ms_p50", percentile(.5)},
      {"per_pair_ms_p95", percentile(.95)},
      {"measurement_status",
       measurement ? measurement->version() : "unavailable"},
      {"model_status",
       cfg.detector == "model"
           ? "actual_model"
           : (cfg.detector == "replay"
                  ? "detection_replay"
                  : (cfg.detector == "module-test" ? "integration-test"
                                                   : "unavailable"))},
      {"hardware_status",
       cfg.motion == "pcie" ? "device_transport_used_requires_board_acceptance"
                            : "not_executed"},
      {"detector_statistics",
       scheduler ? scheduler->statistics() : Json{{"status", "unavailable"}}}};
  writer.finish(summary);
  return summary;
}
} // namespace pipeline
