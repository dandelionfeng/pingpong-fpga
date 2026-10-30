// Actual FPGA seven-stage Mask -> B; original RK frame cache -> native RKNN.
#include "pipeline/pipeline.hpp"
#include "pipeline/hand_schedule.hpp"
#include "mask_release.hpp"
#include "motion7_dma.hpp"
#include "selected_ball_detector.hpp"
#include "capture_session.hpp"
#include "kinematic_probe.hpp"
#ifdef PIPELINE_WITH_TESO
#include "teso.hpp"
#endif
#include <opencv2/imgproc.hpp>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <cstring>
#include <fstream>
#include <future>
#include <iostream>
#include <numeric>
#include <cstdlib>
#include <mutex>
#include <sched.h>
#include <time.h>
using namespace pipeline;
namespace {
double ms(Clock::time_point t){return std::chrono::duration<double,std::milli>(Clock::now()-t).count();}
double processCpuMs(){timespec t{};if(clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&t))throw std::runtime_error("process CPU clock");return t.tv_sec*1000.+t.tv_nsec/1e6;}
void pin(int cpu){if(!std::getenv("CHAIN_PIN"))return;cpu_set_t mask;CPU_ZERO(&mask);CPU_SET(cpu,&mask);if(sched_setaffinity(0,sizeof(mask),&mask))throw std::runtime_error("CPU affinity failed");}
Json stats(std::vector<double> v){if(v.empty())return Json::object();std::sort(v.begin(),v.end());return {{"count",v.size()},{"mean_ms",std::accumulate(v.begin(),v.end(),0.)/v.size()},{"p50_ms",v[(v.size()-1)/2]},{"p95_ms",v[size_t(.95*(v.size()-1))]},{"max_ms",v.back()}};}
using Dma=Motion7Dma;
struct Ready {FramePtr frame;MotionResult motion;double inputMs=0,dmaMs=0;Clock::time_point ingress;};
struct Stream {
  BoundedQueue<Ready> loaded{2},ready{2};
  std::thread loader,transfer;
  std::mutex mutex;std::string error;
  std::atomic<bool> stopping{false};
  void fail(const std::exception&e){std::lock_guard<std::mutex> lock(mutex);error=e.what();stopping=true;loaded.close();ready.close();}
  ~Stream(){stopping=true;loaded.close();ready.close();if(loader.joinable())loader.join();if(transfer.joinable())transfer.join();}
};
}
int main(int argc,char **argv){try{
  if(argc!=10)throw std::runtime_error("Usage: unified_chain_bench INPUT CAL MODEL NEW_OUT batch|async|none DMA_0_1 LIMIT_0_ALL REPEAT PRELOAD_0_1");
  Path out=utf8Path(argv[4]);if(std::filesystem::exists(out))throw std::runtime_error("Choose new output");std::filesystem::create_directories(out);
  std::string mode=argv[5];if(mode!="batch"&&mode!="async"&&mode!="none")throw std::runtime_error("Mode");
  bool useDma=std::stoi(argv[6])!=0,preload=std::stoi(argv[9])!=0;
  size_t limit=std::stoull(argv[7]),repeat=std::stoull(argv[8]);if(!repeat||repeat>100)throw std::runtime_error("Repeat");
  cv::setNumThreads(std::getenv("CHAIN_CV_THREADS")?std::stoi(std::getenv("CHAIN_CV_THREADS")):1);
  bool streaming=std::getenv("CHAIN_STREAMING")!=nullptr;
  const char *cameraDevice=std::getenv("CHAIN_CAMERA");
  const bool camera=cameraDevice && *cameraDevice;
  field_capture::FitStop fitStop;
  MaskRelease handGate;handMaskConfirmed=false;handKinematicConfirmed=false;
  KinematicProbe kinematicProbe;
  field_preprocess::Inline inlinePreprocess;
  const bool stopHandOnMask=std::getenv("CHAIN_HAND_STOP_ON_MASK") && std::string(std::getenv("CHAIN_HAND_STOP_ON_MASK"))=="1";
  Json gateResult=Json::object();size_t handCalls=0,handStrideSkips=0,handStoppedSkips=0,handKinematicSkips=0;
  fitStop.enabled=camera || (std::getenv("CHAIN_AUTOSTOP_FIT") && std::string(std::getenv("CHAIN_AUTOSTOP_FIT"))=="1");
  double captureSeconds=std::getenv("CHAIN_CAPTURE_MAX_SECONDS")?std::stod(std::getenv("CHAIN_CAPTURE_MAX_SECONDS")):30.;
  if(camera && (preload || !streaming || !std::isfinite(captureSeconds) || captureSeconds<=0 || captureSeconds>300))
    throw std::runtime_error("Camera requires streaming, no preload, and capture duration 0..300 seconds");
  std::signal(SIGINT,field_capture::interrupt);std::signal(SIGTERM,field_capture::interrupt);
  std::string stopReason="input_complete";
  double paceFps=std::getenv("CHAIN_PACE_FPS")?std::stod(std::getenv("CHAIN_PACE_FPS")):(mode=="async"?60.:0.);
  if(!std::isfinite(paceFps)||paceFps<0||paceFps>240)throw std::runtime_error("Invalid pace FPS");
  if(streaming && (repeat!=1 || preload))throw std::runtime_error("Streaming uses one file pass and bounded queues, without preload");
  setenv("PIPELINE_B_LIVE_EVENTS",mode=="async"?"1":"0",1);
  setMeasurementCalibration(utf8Path(argv[2]));setDetectorConfiguration(utf8Path(argv[3]));auto registry=moduleRegistry();
  auto b=registry.measurement();auto detector=mode=="none"?nullptr:registry.detector();
  const bool parallelEyes=std::getenv("CHAIN_PARALLEL_EYES") && std::string(std::getenv("CHAIN_PARALLEL_EYES"))=="1";
  if(parallelEyes && (mode!="batch" || !std::getenv("CHAIN_HAND_STRIDE") || std::string(std::getenv("CHAIN_HAND_STRIDE"))!="1" ||
     !std::getenv("CHAIN_HAND_STOP_ON_MASK") || std::string(std::getenv("CHAIN_HAND_STOP_ON_MASK"))!="0"))
    throw std::runtime_error("Parallel eyes experiment requires batch, hand stride1, no mask stopping");
  auto rightDetector=parallelEyes?registry.detector():nullptr;

  Json tesoRuntime={{"requested",std::getenv("CHAIN_TESO")&&std::string(std::getenv("CHAIN_TESO"))=="1"},{"applied",0},{"fallback","existing_calibration"}};
#ifdef PIPELINE_WITH_TESO
  std::unique_ptr<teso::Online> onlineTeso;
  std::optional<teso::Proposal> pendingTeso;
  if(std::getenv("CHAIN_TESO") && std::string(std::getenv("CHAIN_TESO"))=="1")
  {try{
    teso::Settings settings;
    if(std::getenv("CHAIN_TESO_STRIDE"))settings.sample_stride=std::stoi(std::getenv("CHAIN_TESO_STRIDE"));
    if(settings.sample_stride<1||settings.sample_stride>600)throw std::runtime_error("Invalid TESO sampling stride");
    onlineTeso=std::make_unique<teso::Online>(Json::parse(readText(utf8Path(argv[2]))),settings);
  }catch(const std::exception&e){tesoRuntime["disabled_reason"]="initialization_error";tesoRuntime["error"]=e.what();}}
#else
  tesoRuntime["disabled_reason"]="runtime_not_built";
#endif
  if(detector && std::getenv("CHAIN_BALL_MODEL"))detector=std::make_unique<SelectedBallDetector>(std::move(detector),std::getenv("CHAIN_BALL_MODEL"));
  if(repeat!=1)throw std::runtime_error("ABM7 validation uses one ordered clip per hardware reset");
  pin(4); // The C worker inherits this big core; the caller moves to another below.
  std::unique_ptr<DetectorScheduler> scheduler;
  if(mode=="async")scheduler=std::make_unique<DetectorScheduler>(std::move(detector),30,2000,1,32);
  if(scheduler)scheduler->onDiscard=[&](const DetectorContext &c){b->discardDetectionFrame(c.meta);};
  pin(6);
  std::unique_ptr<Dma> dma;if(useDma)dma=std::make_unique<Dma>();
  CpuMotion motion;std::unique_ptr<FrameSource> source;
  std::unique_ptr<field_capture::MjpegArchive> recording;
  if(camera) {
    std::filesystem::copy_file(utf8Path(argv[2]),out/"calibration.json");
    std::filesystem::copy_file(utf8Path(argv[3]),out/"model-config.json");
    recording=std::make_unique<field_capture::MjpegArchive>(out);
    const std::string exposureArg=std::getenv("CHAIN_CAMERA_EXPOSURE")?std::getenv("CHAIN_CAMERA_EXPOSURE"):"auto";
    size_t exposureUsed=0;
    const int exposure=exposureArg=="auto"?0:std::stoi(exposureArg,&exposureUsed);
    if(exposureArg!="auto" && exposureUsed!=exposureArg.size())throw std::runtime_error("Invalid exposure: use auto or a positive integer");
    auto capture=std::make_unique<V4l2FrameSource>(cameraDevice,nativeV4l2Syscalls(),exposure,"MJPG");
    writeText(out/"camera-settings.json",capture->exposureConfiguration().dump(2));
    capture->observeMjpeg([&](const Meta &meta,const std::vector<uint8_t> &jpeg){recording->append(meta,jpeg);});
    source=std::move(capture);
  } else source=std::make_unique<FileFrameSource>(utf8Path(argv[1]));
  std::vector<FramePtr> cache;
  if(preload){auto begin=Clock::now();for(;;){auto r=source->next();if(r.end)break;if(!r.frame||!r.error.empty())throw std::runtime_error(r.error);cache.push_back(r.frame);if(limit&&cache.size()==limit)break;}std::cout<<"PRELOADED "<<cache.size()<<" pairs in "<<ms(begin)<<" ms\n";}
  std::ofstream frames(out/"frames.jsonl"),detections(out/"detections.jsonl"),updates(out/"measurement-updates.jsonl");
  std::ofstream tesoLog(out/"online-teso.jsonl");
  std::ofstream masks(out/"fpga-mask-sequence-lsb.bin",std::ios::binary);
  std::ofstream refinedMasks;if(inlinePreprocess.enabled())refinedMasks.open(out/"preprocess-mask-sequence-lsb.bin",std::ios::binary);
  std::map<std::string,std::vector<double>> times;std::map<std::string,int> states,detstates,classes;
  std::map<uint64_t,int64_t> ingressNs;
  size_t count=0,dc=0;std::atomic<bool> stop{false};auto start=Clock::now();double cpuStart=processCpuMs(),mainCpu=0;
  std::unique_ptr<Stream> stream;
  if(streaming){
    stream=std::make_unique<Stream>();
    stream->loader=std::thread([&]{try{
      pin(7);
      for(size_t i=0;!stream->stopping && (!limit||i<limit);++i){
        if(field_capture::interrupted || (camera && Clock::now()-start>=std::chrono::duration<double>(captureSeconds)))break;
        Ready item;item.ingress=Clock::now();auto r=source->next();item.inputMs=ms(item.ingress);
        if(r.end)break;if(!r.frame||!r.error.empty())throw std::runtime_error(r.error);item.frame=r.frame;
        if(paceFps>0)std::this_thread::sleep_until(start+std::chrono::nanoseconds(int64_t(i*1e9/paceFps)));
        if(!stream->loaded.push(std::move(item)))break;
      }
      stream->loaded.close();
    }catch(const std::exception&e){stream->fail(e);}});
    stream->transfer=std::thread([&]{try{
      pin(3);
      while(!stream->stopping){auto item=stream->loaded.pop(std::chrono::milliseconds(100));if(!item){if(stream->loaded.closed())break;continue;}
        auto phase=Clock::now();if(dma)item->motion=dma->process(*item->frame);item->dmaMs=ms(phase);
        if(!stream->ready.push(std::move(*item)))break;
      }
      stream->ready.close();
    }catch(const std::exception&e){stream->fail(e);}});
  }
  auto accept=[&](const std::vector<DetectionResult>&ds){
    auto begin=Clock::now();
    if(stopHandOnMask)handGate.acceptGateHints(ds);
    inlinePreprocess.accept(ds);
    for(const auto &d:ds){
      ++dc;++detstates[d.status];for(const auto &box:d.boxes)++classes[box.value("class","")];
      if(d.diagnostics.value("hand_racket_invoked",true))++handCalls;
      else if(d.diagnostics.value("hand_racket_skip_reason",std::string())=="mask_confirmed")++handStoppedSkips;
      else if(d.diagnostics.value("hand_racket_skip_reason",std::string())=="kinematic_candidate")++handKinematicSkips;
      else ++handStrideSkips;
      Json diagnostic=d.diagnostics;
      if(ingressNs.count(d.meta.pair_id))diagnostic["input_to_detection_ms"]=(d.completed_ns-ingressNs.at(d.meta.pair_id))/1e6;
      detections<<Json{{"meta",metaJson(d.meta)},{"eye",int(d.eye)},{"task_id",d.task_id},{"generation",d.generation},{"completed_ns",d.completed_ns},{"reference_id",d.reference_id},{"reference_valid",d.reference_valid},{"reference_timestamp_ns",d.reference_timestamp_ns},{"status",d.status},{"backend",d.backend},{"diagnostics",diagnostic},{"boxes",d.boxes}}.dump()<<'\n';
      for(auto key:{"infer_ms","queue_wait_ms","worker_wall_ms","submit_to_complete_ms","input_to_detection_ms"})
        if(diagnostic.contains(key))times[std::string("c_")+key].push_back(diagnostic[key].get<double>());
      if(diagnostic.contains("infer_ms"))times["c_infer"].push_back(diagnostic["infer_ms"].get<double>());
      if(diagnostic.contains("rknn_graph_ms"))for(auto it=diagnostic["rknn_graph_ms"].begin();it!=diagnostic["rknn_graph_ms"].end();++it)
        times["graph/"+it.key()].push_back(it.value().get<double>());
    }
    b->acceptDetections(ds);
    for(const auto &u:b->takeUpdates()){
      Json update=u;auto id=u.value("source_pair_id",uint64_t(0));
      if(ingressNs.count(id)){double latency=(monotonicNs()-ingressNs.at(id))/1e6;update["input_to_measurement_update_ms"]=latency;times["input_to_measurement_update"].push_back(latency);}
      updates<<update.dump()<<'\n';if(u.contains("measurement"))fitStop.observe(u["measurement"],id);
    }
    if(!ds.empty())times["b_async_completion_apply"].push_back(ms(begin));
  };
  int64_t clipSpan=0;uint64_t idSpan=0;
  double mainElapsed=0;
  for(size_t rep=0;rep<repeat;++rep){
    if(rep){motion.reset();b=registry.measurement();dynamic_cast<FileFrameSource&>(*source).seek(0);}
    size_t index=0;
    for(;;){
      if(field_capture::interrupted || fitStop.due()) {
        stopReason=field_capture::interrupted?"manual_stop":"flight_fit_complete";
        if(stream){stream->stopping=true;stream->loaded.close();stream->ready.close();}
        break;
      }
      FramePtr frame;MotionResult hardwareMotion;double inputMs=0,streamDmaMs=0;auto ingress=Clock::now();
      if(streaming){
        auto item=stream->ready.pop(std::chrono::milliseconds(100));
        if(!item){if(stream->ready.closed())break;continue;}
        frame=item->frame;hardwareMotion=std::move(item->motion);inputMs=item->inputMs;streamDmaMs=item->dmaMs;ingress=item->ingress;
      } else if(preload){if(index>=cache.size())break;frame=cache[index];}
      else{auto t=Clock::now();auto r=source->next();inputMs=ms(t);if(r.end)break;if(!r.frame||!r.error.empty())throw std::runtime_error(r.error);frame=r.frame;}
      if(limit&&index>=limit)break;
      auto sourceMeta=frame->meta;
      ingressNs[frame->meta.pair_id]=std::chrono::duration_cast<std::chrono::nanoseconds>(ingress.time_since_epoch()).count();
      if(rep){auto copy=std::make_shared<FramePair>();copy->meta=frame->meta;copy->original=frame->original;copy->search=frame->search;copy->meta.pair_id+=rep*idSpan;copy->meta.timestamp_ns+=rep*clipSpan;for(int e=0;e<2;++e){copy->meta.camera_frame_id[e]+=rep*idSpan;copy->meta.eye_timestamp_ns[e]+=rep*clipSpan;}frame=copy;}
      if(paceFps>0)std::this_thread::sleep_until(start+std::chrono::nanoseconds(int64_t(count*1e9/paceFps)));
      auto total=Clock::now(),phase=total;
      MotionResult m;
      if(dma)m=streaming?std::move(hardwareMotion):dma->process(*frame);
      double dmaMs=streaming?streamDmaMs:ms(phase);phase=Clock::now();
      if(!dma)m=motion.process(*frame);if(!m.valid)throw std::runtime_error(m.error);
      std::array<cv::Mat,2> rawMasks{m.eyes[0].stages[6],m.eyes[1].stages[6]};
      double motionMs=ms(phase);phase=Clock::now();
      inlinePreprocess.apply(*frame,m);double inlineMs=ms(phase);phase=Clock::now();
      double tesoMs=0;
#ifdef PIPELINE_WITH_TESO
      if(onlineTeso){try{
        onlineTeso->submit(*frame,m);
        if(auto next=onlineTeso->take())pendingTeso=std::move(next);
        if(pendingTeso && pendingTeso->source_time_ns<=frame->meta.timestamp_ns){
          auto bytes=pendingTeso->calibration.dump();auto hash=sha256(std::vector<uint8_t>(bytes.begin(),bytes.end()));
          // Persist provenance before publishing; a failed optional write keeps the old calibration.
          writeText(out/("teso-calibration-"+hash+".json"),bytes);
          if(b->tryOnlineCalibration(pendingTeso->calibration,hash)){
            tesoRuntime["applied"]=tesoRuntime["applied"].get<uint64_t>()+1;
            tesoLog<<Json{{"applied_before_pair_id",frame->meta.pair_id},{"source_pair_id",pendingTeso->source_pair_id},
              {"calibration_sha256",hash},{"validation",pendingTeso->validation}}.dump()<<'\n';pendingTeso.reset();
          }
        }
      }catch(const std::exception&e){tesoRuntime["disabled_reason"]="optional_update_error";tesoRuntime["error"]=e.what();onlineTeso->finish();tesoRuntime["last_statistics"]=onlineTeso->statistics();onlineTeso.reset();pendingTeso.reset();}}
      tesoMs=ms(phase);
#endif
      phase=Clock::now();
      std::vector<DetectionResult> ds;
      if(mode=="batch"){
        if(parallelEyes) {
          std::array<std::future<DetectionResult>,2> jobs;
          for(int e=0;e<2;++e)jobs[e]=std::async(std::launch::async,[&,e](){
            pin(4+e);
            DetectorContext c;c.meta=frame->meta;c.eye=static_cast<Eye>(e);c.gray=frame->original[e];c.original_size=c.gray.size();c.task_id=2*count+e+1;c.generation=1;c.submitted_ns=monotonicNs();for(int k=0;k<2;++k){c.reference_id[k]=m.eyes[k].reference_id;c.reference_valid[k]=m.eyes[k].reference_valid;c.reference_timestamp_ns[k]=m.eyes[k].reference_timestamp_ns;}auto detected=(e==0?detector:rightDetector)->infer(c,stop,2000);detected.completed_ns=monotonicNs();return detected;
          });
          // Join and publish in original left/right order; never drop a task.
          for(int e=0;e<2;++e)ds.push_back(jobs[e].get());
        } else {
        for(int e=0;e<2;++e){DetectorContext c;c.meta=frame->meta;c.eye=static_cast<Eye>(e);c.gray=frame->original[e];c.original_size=c.gray.size();c.task_id=2*count+e+1;c.generation=1;c.submitted_ns=monotonicNs();for(int k=0;k<2;++k){c.reference_id[k]=m.eyes[k].reference_id;c.reference_valid[k]=m.eyes[k].reference_valid;c.reference_timestamp_ns[k]=m.eyes[k].reference_timestamp_ns;}auto detected=detector->infer(c,stop,2000);detected.completed_ns=monotonicNs();ds.push_back(std::move(detected));}
        }
        accept(ds);
      }else if(scheduler){ds=scheduler->poll();accept(ds);if(scheduler->submitStereo(*frame,false,&m))b->retainDetectionFrame(frame,m);}
      double cMs=ms(phase);phase=Clock::now();
      auto measured=b->process(*frame,m,ds);double bMs=ms(phase);
      if(stopHandOnMask && !handMaskConfirmed.load()) {
        auto gt=Clock::now();gateResult=handGate.updateGate(*frame,m);times["mask_hand_stop_gate"].push_back(ms(gt));
        if(gateResult.value("accepted",false)){gateResult["confirmed_at_monotonic_ns"]=monotonicNs();handMaskConfirmed=true;}
      }
      if(stopHandOnMask)measured["hand_stop_gate"]=gateResult;
      if(measured.contains("events")&&measured["events"].contains("mask_release_only_ms"))times["legacy_mask_release_only"].push_back(measured["events"]["mask_release_only_ms"].get<double>());
      if(kinematicProbe.eligible(measured)) {
        frames.flush();detections.flush();auto probeBegin=Clock::now();
        kinematicProbe.run(out,utf8Path(argv[1]),utf8Path(argv[2]),*frame,measured);
        times["online_kinematic_probe"].push_back(ms(probeBegin));
      }
      fitStop.observe(measured,frame->meta.pair_id);
      ++states[measured.value("status","unknown")];
      for(int e=0;e<2;++e){auto packed=packMask(rawMasks[e]);masks.write(reinterpret_cast<const char*>(packed.data()),packed.size());
        if(refinedMasks.is_open()){auto refined=packMask(m.eyes[e].stages[6]);refinedMasks.write(reinterpret_cast<const char*>(refined.data()),refined.size());}}
#ifdef PIPELINE_WITH_TESO
      measured["online_teso_enabled"]=bool(onlineTeso);
      measured["teso_pending_idle_boundary"]=bool(pendingTeso);
#endif
      Json timing={{"input_decode_hash_resize",inputMs},{"fpga_mask_dma",dmaMs},{"cpu_motion_fallback",motionMs},{"teso_submit_apply",tesoMs},{"c_sync_or_async_submit",cMs},{"b_measure",bMs},{"main",ms(total)}};
      timing["inline_preprocess"]=inlineMs;
      timing["load_to_measurement_latency"]=ms(ingress);
      for(auto it=timing.begin();it!=timing.end();++it)times[it.key()].push_back(it.value().get<double>());
      frames<<Json{{"meta",metaJson(frame->meta)},{"source_meta",metaJson(sourceMeta)},{"replay_iteration",rep},{"fpga_h2c_bytes",useDma?2*Dma::input_bytes:0},{"fpga_c2h_bytes",useDma?2*Dma::output_bytes:0},{"motion_backend",m.backend},{"reference_id",{m.eyes[0].reference_id,m.eyes[1].reference_id}},{"reference_valid",{m.eyes[0].reference_valid,m.eyes[1].reference_valid}},{"reference_timestamp_ns",{m.eyes[0].reference_timestamp_ns,m.eyes[1].reference_timestamp_ns}},{"timings_ms",timing},{"measurement",measured}}.dump()<<'\n';
      ++count;++index;
      if(rep==0){idSpan=std::max(idSpan,frame->meta.pair_id+1);clipSpan=std::max(clipSpan,frame->meta.timestamp_ns-sourceMeta.timestamp_ns);}
    }
    mainElapsed=ms(start);mainCpu=processCpuMs()-cpuStart;
    if(streaming){stream->loader.join();stream->transfer.join();if(!stream->error.empty())throw std::runtime_error(stream->error);}
    if(camera){source.reset();recording->finish();if(stopReason=="input_complete")stopReason=field_capture::interrupted?"manual_stop":"capture_timeout";}
    // Join the C worker before replacing the B history at a clip boundary.
    if(scheduler){
      scheduler->finish();auto deadline=Clock::now()+std::chrono::seconds(10);
      while(true){auto ds=scheduler->poll();accept(ds);auto status=scheduler->statistics();
        if(status.at("done").get<bool>() && status.at("completed_pending").get<size_t>()==0)break;
        if(Clock::now()>deadline)throw std::runtime_error("C completion drain timed out");
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
      if(rep+1<repeat)throw std::runtime_error("Async repeat requires a fresh scheduler; use one full clip");
    }
    if(rep==0&&preload&&cache.size()>1){clipSpan=cache.back()->meta.timestamp_ns-cache.front()->meta.timestamp_ns+16666667;}
  }
  double elapsed=ms(start);Json summary={{"status","passed"},{"mode",mode},{"pairs",count},{"detections",dc},{"elapsed_ms",elapsed},{"pairs_per_second",1000.*count/elapsed},{"eye_tasks_per_second",1000.*dc/elapsed},{"dma",useDma},{"fpga_h2c_bytes_per_pair",useDma?2*Dma::input_bytes:0},{"fpga_c2h_bytes_received",useDma?count*2*Dma::output_bytes:0},{"fpga_function","actual Gaussian-diff-threshold-erode-dilate-dilate-erode; two-eye reference in ERAM; ABM7 v1"},{"preloaded",preload},{"b_status",states},{"c_status",detstates},{"c_boxes",classes},{"timings",Json::object()}};
  summary["cpu_compared_pairs"]=dma?dma->compared_pairs:0;
  if(dma)summary["fpga_preprocess"]=dma->configuration();summary["inline_preprocess"]=inlinePreprocess.configuration();
  const auto modelInfo=Json::parse(readText(utf8Path(argv[3]))).value("models",Json::object());
  const auto unifiedModel=modelInfo.value("unified",Json::object()).value("path",std::string("unavailable"));
  summary["selected_ball_model"]=std::getenv("CHAIN_BALL_MODEL")?std::string(std::getenv("CHAIN_BALL_MODEL")):modelInfo.value("v6_ball",Json::object()).value("path",unifiedModel);
  summary["hand_racket_model"]=unifiedModel;
  summary["hand_schedule"]={{"stride",std::getenv("CHAIN_HAND_STRIDE")?std::stoi(std::getenv("CHAIN_HAND_STRIDE")):1},
    {"stop_on_mask",stopHandOnMask},{"hand_eye_calls",handCalls},{"stride_eye_skips",handStrideSkips},{"after_mask_eye_skips",handStoppedSkips},
    {"mask_gate",gateResult},{"scope","one clip/session; new process resets latch; V6 runs on every selected eye task"}};
#ifdef PIPELINE_WITH_TESO
  if(onlineTeso){auto closing=Clock::now();onlineTeso->finish();tesoRuntime["shutdown_wait_ms"]=ms(closing);summary["online_teso"]=onlineTeso->statistics();}
#endif
  summary["teso_runtime"]=tesoRuntime;
  if(scheduler)summary["scheduler"]=scheduler->statistics();
  summary["final_event"]=fitStop.event;
  summary["final_event_reported_pair_id"]=fitStop.reported_pair;
  summary["latency_scope"]="recorded-file ingress to result publication, including queueing; result validity retained per record";
  bool passed=count>0 && (mode=="none" || (dc>0 && detstates.size()==1 && detstates.count("ok")));
  if(scheduler){auto s=scheduler->statistics();passed &= s.at("done").get<bool>() && s.at("submitted").get<size_t>()==s.at("replaced").get<size_t>()+dc;}
  summary["status"]=passed?"passed":"failed";
  summary["streaming"]=streaming;summary["main_elapsed_ms"]=mainElapsed;summary["main_pairs_per_second"]=count*1000./mainElapsed;
  summary["pace_pairs_per_second"]=paceFps;
  summary["main_process_cpu_ms"]=mainCpu;
  summary["main_process_cpu_ms_per_pair"]=mainCpu/std::max(size_t(1),count);
  summary["main_process_cpu_percent_one_core"]=100.*mainCpu/mainElapsed;
  summary["main_process_cpu_percent_all_8_cores"]=100.*mainCpu/mainElapsed/8.;
  summary["fpga_function"]=useDma?"physical Gaussian and two-eye ERAM reference; selected Mask mode is recorded in fpga_preprocess":"RK CPU integer seven-stage fallback; no FPGA in this case";
  if(streaming){summary["input_queue_peak"]=stream->loaded.peak();summary["dma_queue_peak"]=stream->ready.peak();}
  summary["input_source"]=camera?"camera":"file";
  summary["stop_reason"]=stopReason;
  summary["hand_kinematic_stop"]=kinematicProbe.state();
  summary["hand_schedule"]["after_kinematic_eye_skips"]=handKinematicSkips;
  summary["auto_stop_after_fit"]=fitStop.enabled;
  if(camera)summary["recorded_pairs"]=recording->size();
  for(const auto &item:times)summary["timings"][item.first]=stats(item.second);
  frames.flush();detections.flush();updates.flush();tesoLog.flush();masks.flush();
  writeText(out/"summary.json",summary.dump(2));
  if(camera) {
    writeText(out/"capture-complete.json",Json{{"schema_version",1},{"stop_reason",stopReason},{"run_status",summary["status"]},
      {"recorded_pairs",recording->size()},{"processed_pairs",count},{"fit_valid",!fitStop.event.is_null()},
      {"final_event",fitStop.event},{"input_manifest","input/manifest.json"},
      {"calibration_sha256",fileSha256(utf8Path(argv[2]))},{"model_config_sha256",fileSha256(utf8Path(argv[3]))}}.dump(2));
  }
  std::cout<<summary.dump(2)<<'\n';return passed?0:1;
}catch(const std::exception&e){std::cerr<<"CHAIN_FAILED "<<e.what()<<'\n';return 1;}}
