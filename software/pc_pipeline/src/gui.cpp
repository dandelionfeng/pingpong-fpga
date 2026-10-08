#include "pipeline/pipeline.hpp"
#include <QApplication>
#include <QComboBox>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QMainWindow>
#include <QMessageBox>
#include <QMouseEvent>
#include <QOpenGLWindow>
#include <QPainter>
#include <QPushButton>
#include <QScreen>
#include <QSlider>
#include <QStandardPaths>
#include <QTest>
#include <QTimer>
#include <QUuid>
#include <QVBoxLayout>
#include <future>
using namespace pipeline;
static Path fromQt(const QString &text) {
  return utf8Path(text.toUtf8().toStdString());
}
static QString toQt(const std::string &text) {
  return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}
static QImage imageOf(const cv::Mat &image) {
  return QImage(image.data, image.cols, image.rows,
                static_cast<int>(image.step), QImage::Format_Grayscale8)
      .copy();
}
struct ViewPacket {
  FramePtr frame;
  MotionResult motion;
  size_t index = 0;
  std::string error;
};
class ViewWorker {
public:
  explicit ViewWorker(Path manifest)
      : manifest_(std::move(manifest)), thread_([this] { loop(); }) {}
  ~ViewWorker() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stop_ = true;
      condition_.notify_all();
    }
    thread_.join();
  }
  void request(size_t index) {
    std::lock_guard<std::mutex> lock(mutex_);
    target_ = index;
    pending_ = true;
    condition_.notify_all();
  }
  std::optional<ViewPacket> poll() {
    std::lock_guard<std::mutex> lock(mutex_);
    auto p = std::move(packet_);
    packet_.reset();
    return p;
  }

private:
  void loop() {
    try {
      FileFrameSource source(manifest_);
      CpuMotion cpu;
      FrameCache cache;
      size_t position = 0;
      while (true) {
        size_t target;
        {
          std::unique_lock<std::mutex> lock(mutex_);
          condition_.wait(lock, [&] { return stop_ || pending_; });
          if (stop_)
            break;
          target = target_;
          pending_ = false;
        }
        if (target < position) {
          source.seek(0);
          cpu.reset();
          cache.clear();
          position = 0;
        }
        ViewPacket result;
        while (position <= target) {
          auto read = source.next();
          result.index = position++;
          if (read.end)
            throw std::runtime_error("seek beyond input");
          if (!read.error.empty()) {
            result.error = read.error;
            result.frame.reset();
            continue;
          }
          cache.put(read.frame);
          result.frame = read.frame;
          result.motion = cpu.process(*read.frame);
          result.error = result.motion.error;
          {
            std::lock_guard<std::mutex> lock(mutex_);
            if (stop_)
              return;
            if (pending_ && target_ != target)
              break;
          }
        }
        {
          std::lock_guard<std::mutex> lock(mutex_);
          packet_ = std::move(result);
        }
      }
    } catch (const std::exception &e) {
      std::lock_guard<std::mutex> lock(mutex_);
      packet_ = ViewPacket{{}, {}, 0, e.what()};
    }
  }
  Path manifest_;
  std::mutex mutex_;
  std::condition_variable condition_;
  bool stop_ = false, pending_ = false;
  size_t target_ = 0;
  std::optional<ViewPacket> packet_;
  std::thread thread_;
};
class PairCanvas final : public QOpenGLWindow {
public:
  std::function<void(Eye, cv::Point2d)> selected;
  void setBoxes(std::array<Json, 2> boxes) {
    boxes_ = std::move(boxes);
    update();
  }
  void setImages(const cv::Mat &left, const cv::Mat &right, bool search) {
    images_ = {imageOf(left), imageOf(right)};
    search_ = search;
    update();
  }
  QPoint testClick() const {
    return regions_[0].topLeft().toPoint() +
           QPoint(8, static_cast<int>(regions_[0].height() / 2));
  }

protected:
  void paintGL() override {
    QPainter p(this);
    p.fillRect(QRect(0, 0, width(), height()), QColor("#141b24"));
    for (int e = 0; e < 2; ++e) {
      QRectF panel(e * width() / 2. + 8, 34, width() / 2. - 16, height() - 42);
      if (images_[e].isNull())
        continue;
      QSizeF size = images_[e].size();
      size.scale(panel.size(), Qt::KeepAspectRatio);
      regions_[e] = QRectF(QPointF(panel.center().x() - size.width() / 2,
                                   panel.center().y() - size.height() / 2),
                           size);
      p.drawImage(regions_[e], images_[e]);
      for (auto &box : boxes_[e]) {
        auto b = box.at("bbox").get<std::vector<double>>();
        auto &r = regions_[e];
        QRectF rectangle(r.x() + b[0] / EyeWidth * r.width(),
                         r.y() + b[1] / EyeHeight * r.height(),
                         b[2] / EyeWidth * r.width(),
                         b[3] / EyeHeight * r.height());
        p.setPen(QPen(QColor("#58dfb3"), 2));
        p.drawRect(rectangle);
        p.drawText(
            rectangle.topLeft() - QPointF(0, 4),
            toQt(box.at("class")) + " " +
                QString::number(box.at("confidence").get<double>(), 'f', 2));
      }
      p.setPen(QColor("#c5d4dd"));
      p.drawText(QPointF(e * width() / 2. + 12, 23),
                 e ? "RIGHT / 右眼" : "LEFT / 左眼");
    }
  }
  void mousePressEvent(QMouseEvent *event) override {
    for (int e = 0; e < 2; ++e)
      if (regions_[e].contains(event->position()) && selected) {
        auto r = regions_[e];
        cv::Point2d pos{(event->position().x() - r.left()) / r.width() *
                            images_[e].width(),
                        (event->position().y() - r.top()) / r.height() *
                            images_[e].height()};
        if (search_)
          pos = searchToOriginal(pos);
        selected(static_cast<Eye>(e), pos);
      }
  }

private:
  std::array<QImage, 2> images_;
  std::array<QRectF, 2> regions_;
  bool search_ = false;
  std::array<Json, 2> boxes_{{Json::array(), Json::array()}};
};
class MainWindow final : public QMainWindow {
public:
  MainWindow() {
    setWindowTitle("蒲公英 · A 双目处理工作台");
    resize(1260, 850);
    auto root = new QWidget;
    auto layout = new QVBoxLayout(root);
    layout->setContentsMargins(18, 16, 18, 14);
    layout->setSpacing(12);
    auto title = new QLabel("双目处理工作台   /   A PIPELINE");
    title->setStyleSheet("font-size:22px;font-weight:600;color:#183f49");
    layout->addWidget(title);
    auto tools = new QHBoxLayout;
    auto package = new QPushButton("导入截图包");
    auto manifest = new QPushButton("打开输入清单");
    save_ = new QPushButton("导出当前帧");
    save_->setObjectName("saveFrame");
    export_ = new QPushButton("运行并导出全序列");
    export_->setObjectName("exportRun");
    cancel_ = new QPushButton("取消导出");
    cancel_->setEnabled(false);
    tools->addWidget(package);
    tools->addWidget(manifest);
    tools->addWidget(save_);
    tools->addWidget(export_);
    tools->addWidget(cancel_);
    tools->addStretch();
    layout->addLayout(tools);
    auto modes = new QHBoxLayout;
    stage_ = new QComboBox;
    stage_->setObjectName("stage");
    stage_->addItems({"原图 Y", "640×360 搜索图", "Gaussian", "帧差", "阈值",
                      "腐蚀 1", "膨胀 1", "膨胀 2", "腐蚀 2 / Mask"});
    motion_ = new QComboBox;
    motion_->addItems({"CPU 整数参考", "模拟 DMA"});
    detector_ = new QComboBox;
    detector_->addItems({"类别检测 unavailable", "检测框回放", "C 实际模型"});
    auto selectReplay = new QPushButton("选择检测框回放");
    modes->addWidget(new QLabel("显示阶段"));
    modes->addWidget(stage_);
    modes->addSpacing(20);
    modes->addWidget(new QLabel("导出运动后端"));
    modes->addWidget(motion_);
    modes->addWidget(detector_);
    modes->addWidget(selectReplay);
    modes->addStretch();
    layout->addLayout(modes);
    canvas_ = new PairCanvas;
    canvas_->selected = [this](Eye eye, cv::Point2d p) {
      centers_[static_cast<int>(eye)] = p;
      render();
    };
    auto panel = new QHBoxLayout;
    auto container = QWidget::createWindowContainer(canvas_);
    container->setMinimumSize(850, 390);
    panel->addWidget(container, 5);
    auto roiColumn = new QVBoxLayout;
    roiColumn->addWidget(new QLabel("同帧原图 ROI · 点击画面选取"));
    for (int e = 0; e < 2; ++e) {
      roiLabels_[e] = new QLabel;
      roiLabels_[e]->setMinimumSize(160, 160);
      roiLabels_[e]->setAlignment(Qt::AlignCenter);
      roiColumn->addWidget(roiLabels_[e]);
    }
    roiInfo_ = new QLabel;
    roiInfo_->setWordWrap(true);
    roiColumn->addWidget(roiInfo_);
    panel->addLayout(roiColumn, 1);
    layout->addLayout(panel, 1);
    auto transport = new QHBoxLayout;
    play_ = new QPushButton("播放");
    play_->setObjectName("play");
    previous_ = new QPushButton("上一帧");
    previous_->setObjectName("previous");
    next_ = new QPushButton("下一帧");
    next_->setObjectName("next");
    slider_ = new QSlider(Qt::Horizontal);
    slider_->setObjectName("seek");
    index_ = new QLabel("— / —");
    transport->addWidget(play_);
    transport->addWidget(previous_);
    transport->addWidget(next_);
    transport->addWidget(slider_, 1);
    transport->addWidget(index_);
    layout->addLayout(transport);
    meta_ = new QLabel("导入 YUY2/GRAY8 输入清单，检查像素、Mask 与来源帧号。");
    meta_->setWordWrap(true);
    layout->addWidget(meta_);
    status_ = new QLabel("软件模式：CPU 文件回放   |   B 测量 unavailable   |  "
                         " 实际模型 unavailable   |   实物验收待接入");
    status_->setWordWrap(true);
    status_->setStyleSheet("padding:8px;background:#e7eff1;color:#264953");
    layout->addWidget(status_);
    setCentralWidget(root);
    setStyleSheet("QMainWindow{background:#f4f7f8} QPushButton{padding:7px "
                  "12px} QComboBox{padding:5px} "
                  "QSlider::handle:horizontal{background:#257f84;border-radius:"
                  "6px;width:13px;margin:-4px 0} "
                  "QSlider::groove:horizontal{height:5px;background:#cfdee1}");
    for (auto b : {save_, export_, play_, previous_, next_})
      b->setEnabled(false);
    connect(package, &QPushButton::clicked, this, [this] {
      auto folder = QFileDialog::getExistingDirectory(
          this, "选择含 export.json 与 pairs.csv 的目录");
      if (folder.isEmpty())
        return;
      try {
        importPackage(fromQt(folder));
      } catch (const std::exception &e) {
        showError(e.what());
      }
    });
    connect(manifest, &QPushButton::clicked, this, [this] {
      auto f = QFileDialog::getOpenFileName(this, "打开输入清单", {},
                                            "JSON (*.json)");
      if (!f.isEmpty())
        try {
          load(fromQt(f));
        } catch (const std::exception &e) {
          showError(e.what());
        }
    });
    connect(stage_, &QComboBox::currentIndexChanged, this,
            [this] { render(); });
    connect(slider_, &QSlider::valueChanged, this, [this](int value) {
      desired_ = value;
      if (worker_)
        worker_->request(static_cast<size_t>(value));
    });
    connect(next_, &QPushButton::clicked, this, [this] {
      setPlaying(false);
      slider_->setValue(std::min(slider_->value() + 1, slider_->maximum()));
    });
    connect(previous_, &QPushButton::clicked, this, [this] {
      setPlaying(false);
      slider_->setValue(std::max(0, slider_->value() - 1));
    });
    connect(play_, &QPushButton::clicked, this,
            [this] { setPlaying(!playing_); });
    connect(save_, &QPushButton::clicked, this, [this] {
      try {
        auto path = chooseOutput("snapshot");
        if (!path.empty())
          saveCurrent(path);
      } catch (const std::exception &e) {
        showError(e.what());
      }
    });
    connect(export_, &QPushButton::clicked, this, [this] {
      try {
        auto path = chooseOutput("sequence");
        if (!path.empty())
          startExport(path);
      } catch (const std::exception &e) {
        showError(e.what());
      }
    });
    connect(cancel_, &QPushButton::clicked, this, [this] {
      if (cancelFlag_)
        cancelFlag_->store(true);
    });
    connect(selectReplay, &QPushButton::clicked, this, [this] {
      auto p = QFileDialog::getOpenFileName(this, "选择检测框回放", {},
                                            "JSON (*.json)");
      if (!p.isEmpty()) {
        replay_ = fromQt(p);
        detector_->setCurrentIndex(1);
        resetDetector();
      }
    });
    connect(detector_, &QComboBox::currentIndexChanged, this,
            [this] { resetDetector(); });
    poll_.setInterval(12);
    connect(&poll_, &QTimer::timeout, this, [this] { tick(); });
    poll_.start();
    playTimer_.setSingleShot(true);
    connect(&playTimer_, &QTimer::timeout, this, [this] {
      if (!playing_)
        return;
      if (desired_ >= slider_->maximum()) {
        setPlaying(false);
        return;
      }
      slider_->setValue(desired_ + 1);
      scheduleNext();
    });
  }
  ~MainWindow() {
    if (cancelFlag_)
      cancelFlag_->store(true);
    if (exportJob_.valid())
      exportJob_.wait();
    worker_.reset();
    detectorWorker_.reset();
    if (previewArchive_)
      previewArchive_->finish(
          {{"status", "closed"}, {"mode", "gui_detection_preview"}});
  }
  void load(Path manifest) {
    setPlaying(false);
    worker_.reset();
    packet_.reset();
    if (detectorWorker_)
      detectorWorker_->reset();
    boxes_ = {Json::array(), Json::array()};
    canvas_->setBoxes(boxes_);
    manifest_ = std::move(manifest);
    auto j = Json::parse(readText(manifest_));
    entries_ = j.at("frames");
    if (entries_.empty())
      throw std::runtime_error("empty input");
    slider_->blockSignals(true);
    slider_->setRange(0, static_cast<int>(entries_.size() - 1));
    slider_->setValue(0);
    slider_->blockSignals(false);
    desired_ = 0;
    worker_ = std::make_unique<ViewWorker>(manifest_);
    worker_->request(0);
    for (auto b : {save_, export_, play_, previous_, next_})
      b->setEnabled(true);
    status_->setText(
        "输入已载入；预览使用 CPU "
        "共用核心。导出按所选后端运行。来源与验证范围写入 run.json。");
  }
  void importPackage(const Path &folder) {
    auto cache = fromQt(
        QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation));
    auto file =
        cache /
        (QUuid::createUuid().toString(QUuid::WithoutBraces).toStdString() +
         ".json");
    importExportPackage(folder, file);
    load(file);
  }
  bool ready(size_t index) const {
    return packet_ && packet_->frame && packet_->index == index;
  }
  bool readyAtLeast(size_t index) const {
    return packet_ && packet_->frame && packet_->index >= index;
  }
  bool hasBoxes() const { return !boxes_[0].empty(); }
  PairCanvas *canvas() { return canvas_; }
  QSlider *slider() { return slider_; }
  bool playing() const { return playing_; }
  bool exporting() const { return exporting_; }
  Json lastExport;
  Path testRoot;
  void setReplay(Path file) {
    replay_ = std::move(file);
    detector_->setCurrentIndex(1);
  }
  void saveCurrent(const Path &path) {
    if (!packet_ || !packet_->frame)
      throw std::runtime_error("no valid frame");
    RunWriter writer(path, {{"save_images", true},
                            {"save_stages", true},
                            {"mode", "gui_cpu_preview"}});
    writer.frame(*packet_->frame, packet_->motion);
    Json rois = Json::array();
    for (int e = 0; e < 2; ++e) {
      auto r = cropRoi(*packet_->frame, static_cast<Eye>(e), centers_[e]);
      writeImage(path /
                     (e ? "selected_roi_right.png" : "selected_roi_left.png"),
                 r.image);
      rois.push_back(
          {{"eye", eyeName(static_cast<Eye>(e))},
           {"pair_id", r.pair_id},
           {"origin", {r.origin.x, r.origin.y}},
           {"valid", {r.valid.x, r.valid.y, r.valid.width, r.valid.height}}});
    }
    writeText(path / "selected-rois.json", rois.dump(2));
    writer.finish(
        {{"status", "passed"}, {"pair_id", packet_->frame->meta.pair_id}});
  }

private:
  void resetDetector() {
    detectorWorker_.reset();
    if (previewArchive_)
      previewArchive_->finish(
          {{"status", "closed"}, {"mode", "gui_detection_preview"}});
    previewArchive_.reset();
    boxes_ = {Json::array(), Json::array()};
    canvas_->setBoxes(boxes_);
    try {
      std::unique_ptr<DetectorBackend> backend;
      if (detector_->currentIndex() == 1) {
        if (replay_.empty())
          throw std::runtime_error("先选择检测框回放 JSON");
        backend = std::make_unique<ReplayDetector>(replay_);
      } else if (detector_->currentIndex() == 2) {
        auto reg = moduleRegistry();
        if (!reg.detector)
          throw std::runtime_error(
              "C 实际模型 unavailable：需要接入 pipeline_c_module");
        backend = reg.detector();
        if (!backend || backend->mode() != "actual-model")
          throw std::runtime_error("C 后端未声明 actual-model");
      } else
        return;
      auto cache = fromQt(QStandardPaths::writableLocation(
          QStandardPaths::AppLocalDataLocation));
      auto path =
          cache / "preview" /
          QUuid::createUuid().toString(QUuid::WithoutBraces).toStdString();
      previewArchive_ = std::make_unique<RunWriter>(
          path, Json{{"save_images", false}, {"mode", backend->mode()}});
      detectorWorker_ = std::make_unique<DetectorScheduler>(std::move(backend));
      if (packet_ && packet_->frame)
        detectorWorker_->submit(*packet_->frame, Eye::Left, false,
                                &packet_->motion);
      status_->setText("检测预览已启用；迟到结果归档至 " +
                       toQt(pathUtf8(path)));
    } catch (const std::exception &e) {
      showError(e.what());
    }
  }
  Path chooseOutput(const char *kind) {
    if (!testRoot.empty())
      return testRoot / kind;
    auto folder = QFileDialog::getExistingDirectory(this, "选择导出父目录");
    if (folder.isEmpty())
      return {};
    return fromQt(folder) /
           (std::string(kind) + "-" +
            QUuid::createUuid().toString(QUuid::WithoutBraces).toStdString());
  }
  void setPlaying(bool on) {
    playing_ = on;
    play_->setText(on ? "暂停" : "播放");
    if (on) {
      if (desired_ == slider_->maximum())
        slider_->setValue(0);
      scheduleNext();
    } else
      playTimer_.stop();
  }
  void scheduleNext() {
    if (!playing_)
      return;
    int delay = 16;
    if (desired_ + 1 < static_cast<int>(entries_.size())) {
      auto a = entries_[desired_].at("timestamp_ns").get<int64_t>(),
           b = entries_[desired_ + 1].at("timestamp_ns").get<int64_t>();
      delay = static_cast<int>(std::clamp((b - a) / 1000000LL, 1LL, 1000LL));
    }
    playTimer_.start(delay);
  }
  void tick() {
    if (worker_) {
      auto p = worker_->poll();
      if (p) {
        if (!p->error.empty()) {
          status_->setText("输入/处理错误：" + toQt(p->error));
          setPlaying(false);
        }
        if (p->frame) {
          if (packet_ && p->index < packet_->index && detectorWorker_)
            detectorWorker_->reset();
          packet_ = std::move(p);
          boxes_ = {Json::array(), Json::array()};
          canvas_->setBoxes(boxes_);
          if (detectorWorker_)
            detectorWorker_->submit(*packet_->frame, Eye::Left, false,
                                    &packet_->motion);
          render();
        }
      }
    }
    if (detectorWorker_)
      for (auto &r : detectorWorker_->poll()) {
        if (previewArchive_)
          previewArchive_->detection(r);
        if (packet_ && r.status == "ok" &&
            r.meta.pair_id == packet_->frame->meta.pair_id &&
            r.meta.timestamp_ns == packet_->frame->meta.timestamp_ns) {
          boxes_[static_cast<int>(r.eye)] = r.boxes;
          canvas_->setBoxes(boxes_);
          status_->setText(
              "检测来源 pair_id=" + QString::number(r.meta.pair_id) + " / " +
              toQt(r.backend) + "；任务 " + QString::number(r.task_id));
        }
      }
    if (exporting_ && exportJob_.wait_for(std::chrono::milliseconds(0)) ==
                          std::future_status::ready) {
      exporting_ = false;
      export_->setEnabled(true);
      cancel_->setEnabled(false);
      try {
        lastExport = exportJob_.get();
        status_->setText(
            "导出 " + toQt(lastExport.value("status", "unknown")) + "；处理 " +
            QString::number(lastExport.value("processed", uint64_t(0))) +
            " 对。B/C 及实物状态见 run.json。");
      } catch (const std::exception &e) {
        showError(e.what());
      }
    }
  }
  void render() {
    if (!packet_ || !packet_->frame)
      return;
    auto &p = *packet_;
    int stage = stage_->currentIndex();
    auto select = [&](int eye) -> const cv::Mat & {
      if (stage == 0)
        return p.frame->original[eye];
      if (stage == 1)
        return p.frame->search[eye];
      auto &image = p.motion.eyes[eye].stages[static_cast<size_t>(stage - 2)];
      return image.empty() ? p.frame->search[eye] : image;
    };
    canvas_->setImages(select(0), select(1), stage != 0);
    QString info;
    for (int e = 0; e < 2; ++e) {
      auto roi = cropRoi(*p.frame, static_cast<Eye>(e), centers_[e]);
      roiLabels_[e]->setPixmap(
          QPixmap::fromImage(imageOf(roi.image))
              .scaled(176, 176, Qt::KeepAspectRatio, Qt::SmoothTransformation));
      info += QString(e ? "右" : "左") + QString("原点 (%1,%2)，有效 %3×%4\n")
                                             .arg(roi.origin.x)
                                             .arg(roi.origin.y)
                                             .arg(roi.valid.width)
                                             .arg(roi.valid.height);
    }
    roiInfo_->setText(info + "ROI 为检查裁块；球心由 B 模块提供。");
    index_->setText(QString("%1 / %2").arg(p.index + 1).arg(entries_.size()));
    auto &m = p.frame->meta;
    meta_->setText(QString("pair_id %1   |   采样 %2 ns   |   reference L:%3 "
                           "R:%4   |   %5\n配置 %6   ·   标定 %7   ·   模型 %8")
                       .arg(m.pair_id)
                       .arg(m.timestamp_ns)
                       .arg(p.motion.eyes[0].reference_id)
                       .arg(p.motion.eyes[1].reference_id)
                       .arg(toQt(m.time_source))
                       .arg(toQt(m.config_version))
                       .arg(toQt(m.calibration_version))
                       .arg(toQt(m.model_version)));
  }
  void startExport(const Path &path) {
    if (exporting_)
      throw std::runtime_error("export already active");
    RunConfig cfg;
    cfg.motion = motion_->currentIndex() == 1 ? "mock-dma" : "cpu";
    cfg.detector = detector_->currentIndex() == 1   ? "replay"
                   : detector_->currentIndex() == 2 ? "model"
                                                    : "none";
    cfg.replay = replay_;
    cancelFlag_ = std::make_shared<std::atomic<bool>>(false);
    cfg.cancellation = cancelFlag_;
    auto input = manifest_;
    exportJob_ = std::async(std::launch::async, [input, path, cfg] {
      return runPipeline(input, path, cfg);
    });
    exporting_ = true;
    export_->setEnabled(false);
    cancel_->setEnabled(true);
    status_->setText("全序列运行中；预览与导出使用相同像素核心。");
  }
  void showError(const std::string &s) {
    status_->setText("错误：" + toQt(s));
    if (testRoot.empty())
      QMessageBox::warning(this, "A Pipeline", toQt(s));
  }
  Path manifest_, replay_;
  Json entries_;
  std::unique_ptr<ViewWorker> worker_;
  std::unique_ptr<DetectorScheduler> detectorWorker_;
  std::unique_ptr<RunWriter> previewArchive_;
  std::array<Json, 2> boxes_{{Json::array(), Json::array()}};
  std::optional<ViewPacket> packet_;
  std::array<cv::Point2d, 2> centers_{{{640, 360}, {640, 360}}};
  PairCanvas *canvas_;
  QLabel *roiLabels_[2]{}, *roiInfo_, *meta_, *status_, *index_;
  QPushButton *save_, *export_, *cancel_, *play_, *previous_, *next_;
  QComboBox *stage_, *motion_, *detector_;
  QSlider *slider_;
  QTimer poll_, playTimer_;
  int desired_ = 0;
  bool playing_ = false, exporting_ = false;
  std::future<Json> exportJob_;
  std::shared_ptr<std::atomic<bool>> cancelFlag_;
};
int main(int argc, char **argv) {
  QApplication app(argc, argv);
  app.setApplicationName("AUsbStereoPipeline");
  MainWindow window;
  auto args = app.arguments();
  bool selfTest = args.contains("--self-test");
  auto value = [&](const QString &name) {
    int i = args.indexOf(name);
    return i >= 0 && i + 1 < args.size() ? args[i + 1] : QString();
  };
  try {
    if (!value("--input").isEmpty())
      window.load(fromQt(value("--input")));
    if (!value("--package").isEmpty())
      window.importPackage(fromQt(value("--package")));
    if (selfTest) {
      window.testRoot = fromQt(value("--output"));
      if (window.testRoot.empty())
        throw std::runtime_error("self-test output required");
      std::filesystem::create_directories(window.testRoot);
    }
    if (!value("--replay").isEmpty())
      window.setReplay(fromQt(value("--replay")));
  } catch (const std::exception &e) {
    writeText(utf8Path("gui-error.json"), Json{{"error", e.what()}}.dump(2));
    return 1;
  }
  window.show();
  QTimer tester;
  int step = 0;
  auto start = Clock::now();
  if (selfTest) {
    tester.setInterval(20);
    QObject::connect(&tester, &QTimer::timeout, &window, [&] {
      try {
        if (Clock::now() - start > std::chrono::seconds(180))
          throw std::runtime_error("GUI self-test deadline");
        if (step == 0 && window.ready(0)) {
          QTest::mouseClick(window.findChild<QPushButton *>("next"),
                            Qt::LeftButton);
          ++step;
        } else if (step == 1 && window.ready(1)) {
          window.slider()->setValue(56);
          ++step;
        } else if (step == 2 && window.ready(56)) {
          window.findChild<QComboBox *>("stage")->setCurrentIndex(2);
          ++step;
        } else if (step == 3 &&
                   (value("--replay").isEmpty() || window.hasBoxes())) {
          QTest::mouseClick(window.canvas(), Qt::LeftButton, Qt::NoModifier,
                            window.canvas()->testClick());
          QTest::mouseClick(window.findChild<QPushButton *>("saveFrame"),
                            Qt::LeftButton);
          window.screen()
              ->grabWindow(window.winId())
              .save(QString::fromStdString(
                  pathUtf8(window.testRoot / "gui.png")));
          window.canvas()->grabFramebuffer().save(
              QString::fromStdString(pathUtf8(window.testRoot / "canvas.png")));
          QTest::mouseClick(window.findChild<QPushButton *>("play"),
                            Qt::LeftButton);
          ++step;
        } else if (step == 4 && window.readyAtLeast(60)) {
          QTest::mouseClick(window.findChild<QPushButton *>("play"),
                            Qt::LeftButton);
          if (window.playing())
            throw std::runtime_error("pause failed");
          window.slider()->setValue(0);
          ++step;
        } else if (step == 5 && window.ready(0)) {
          QTest::mouseClick(window.findChild<QPushButton *>("exportRun"),
                            Qt::LeftButton);
          ++step;
        } else if (step == 6 && !window.exporting()) {
          if (window.lastExport.value("status", "") != "passed" ||
              window.lastExport.value("processed", 0) != 125)
            throw std::runtime_error("GUI sequence export failed");
          writeText(window.testRoot / "gui-test.json",
                    Json{{"status", "passed"},
                         {"checks",
                          {"load", "next", "seek56", "stage", "ROI click",
                           "snapshot", "play", "pause", "seek0", "export125"}},
                         {"export", window.lastExport}}
                        .dump(2));
          tester.stop();
          app.exit(0);
        }
      } catch (const std::exception &e) {
        writeText(
            window.testRoot / "gui-test.json",
            Json{{"status", "failed"}, {"error", e.what()}, {"step", step}}
                .dump(2));
        tester.stop();
        app.exit(1);
      }
    });
    tester.start();
  }
  return app.exec();
}
