#include "pipeline/pipeline.hpp"
#include <opencv2/imgcodecs.hpp>
#include <algorithm>
#include <csignal>
#include <fstream>
#include <iostream>
#include <numeric>

using namespace pipeline;
namespace {
volatile std::sig_atomic_t stop_requested=0;
void stop(int) { stop_requested=1; }
Json grayStats(const FramePair &frame) {
  Json values=Json::array();
  for(const auto &eye:frame.original) {
    cv::Scalar mean,deviation; cv::meanStdDev(eye,mean,deviation);
    values.push_back({{"width",eye.cols},{"height",eye.rows},
                      {"mean",mean[0]},{"stddev",deviation[0]}});
  }
  return values;
}
}
int main(int argc,char **argv) {
  if(argc<3 || argc>5) return 2;
  const std::string exposure_arg=argc>3?argv[3]:"auto";
  const int selected_exposure=exposure_arg=="auto"?0:std::stoi(exposure_arg);
  const std::string selected_format=argc>4?argv[4]:"MJPG";
  const Path output=utf8Path(argv[2]);
  if(std::filesystem::exists(output)) return 3;
  std::filesystem::create_directories(output);
  std::signal(SIGINT,stop); std::signal(SIGTERM,stop);
  Json result={{"scope","actual project V4l2FrameSource MJPG receive/decode/split; no models or scoring"},
               {"device",argv[1]},{"requested_format",selected_format},{"width",2560},{"height",720},
               {"requested_fps",60},{"exposure_absolute",selected_exposure},{"status","failed"}};
  std::ofstream records(output/"frames.jsonl");
  uint64_t frames=0,bytes=0,gaps=0,previous_sequence=0;
  int64_t first_timestamp=0,last_timestamp=0;
  std::map<std::string,int> errors;
  std::vector<double> intervals;
  try {
    FramePtr last;
    const auto setup=Clock::now();
    auto source=std::make_unique<V4l2FrameSource>(argv[1],nativeV4l2Syscalls(),selected_exposure,selected_format);
    result["exposure_configuration"]=source->exposureConfiguration();
    result["setup_ms"]=std::chrono::duration<double,std::milli>(Clock::now()-setup).count();
    const auto start=Clock::now();
    while(!stop_requested && Clock::now()-start<std::chrono::seconds(10)) {
      auto read=source->next();
      if(!read.error.empty() || !read.frame) {++errors[read.error]; continue;}
      const auto sequence=read.meta.camera_frame_id[0];
      const auto stamp=read.meta.timestamp_ns;
      if(frames) {
        if(sequence>previous_sequence+1)gaps+=sequence-previous_sequence-1;
        intervals.push_back((stamp-last_timestamp)/1e6);
      } else {
        first_timestamp=stamp; result["first_sequence"]=sequence;
        result["first_gray_stats"]=grayStats(*read.frame);
        result["first_capture_evidence"]=read.evidence;
      }
      for(int e=0;e<2;++e)
        if(read.frame->original[e].type()!=CV_8UC1 || read.frame->original[e].size()!=cv::Size(1280,720) ||
           read.frame->search[e].type()!=CV_8UC1 || read.frame->search[e].size()!=cv::Size(640,360))
          throw std::runtime_error("Decoded stereo dimensions/type mismatch");
      auto payload=read.evidence.at("bytesused").get<uint64_t>();
      records<<Json{{"pair_id",read.meta.pair_id},{"sequence",sequence},{"timestamp_ns",stamp},
                   {"compressed_bytes",payload},{"capture_format",read.evidence.at("capture_format")},
                   {"source",read.meta.source}}.dump()<<'\n';
      bytes+=payload; ++frames; previous_sequence=sequence; last_timestamp=stamp; last=read.frame;
    }
    result["elapsed_seconds"]=std::chrono::duration<double>(Clock::now()-start).count();
    source.reset(); // Stop streaming before statistics or output processing.
    result["capture_stopped"]=true;
    if(last){
      result["last_gray_stats"]=grayStats(*last);
      cv::Mat preview;cv::hconcat(last->original[0],last->original[1],preview);
      if(!cv::imwrite((output/"preview.jpg").string(),preview))throw std::runtime_error("cannot write camera preview");
    }
    result["status"]=frames ? "received_and_decoded" : "no_decoded_frames";
  }catch(const std::exception &e) {result["error"]=e.what();}
  result["decoded_frames"]=frames; result["compressed_bytes"]=bytes;
  result["last_sequence"]=previous_sequence; result["driver_sequence_gaps"]=gaps;
  result["read_errors"]=errors;
  if(frames>1)result["timestamp_fps"]=(frames-1)*1e9/(last_timestamp-first_timestamp);
  if(!intervals.empty()) {
    result["initial_interval_ms"]=intervals.front();
    result["max_interval_ms"]=*std::max_element(intervals.begin(),intervals.end());
    std::sort(intervals.begin(),intervals.end());
    result["median_interval_ms"]=intervals[intervals.size()/2];
  }
  writeText(output/"summary.json",result.dump(2)); std::cout<<result.dump()<<'\n';
  return frames ? 0 : 1;
}
