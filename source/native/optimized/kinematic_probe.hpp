#pragma once
#include <spawn.h>
#include <sys/wait.h>
#include <cerrno>
#include <fstream>
extern char **environ;
namespace pipeline {
class KinematicProbe {
  std::string mode_="off";
  Json state_=Json::object();
  bool attempted_=false;
public:
  KinematicProbe() {
    if(const char *value=std::getenv("CHAIN_HAND_KINEMATIC_MODE"))mode_=value;
    if(mode_!="off" && mode_!="observe" && mode_!="stop")throw std::runtime_error("Unknown kinematic hand mode");
    state_={{"mode",mode_},{"attempted",false},{"candidate_seen",false},{"stopped",false}};
  }
  bool eligible(const Json &measured)const {
    if(mode_=="off" || attempted_ || !measured.contains("events"))return false;
    const auto &event=measured["events"];
    return event.value("fit_valid",false) && event.contains("release_pixel_evidence") &&
      event["release_pixel_evidence"].value("accepted",false) &&
      event["release_pixel_evidence"].contains("seed_pair_ids");
  }
  void run(const Path &out,const Path &manifest,const Path &calibration,
           const FramePair &frame,const Json &measured) {
    attempted_=true;state_["attempted"]=true;
    const auto begin=Clock::now();
    state_["observed_at_pair_id"]=frame.meta.pair_id;
    try {
      const char *helper=std::getenv("CHAIN_KINEMATIC_HELPER");
      if(!helper || !*helper)throw std::runtime_error("Kinematic helper is not configured");
      const Path context=out/"online-kinematic-context.json";
      const Path result=out/"online-kinematic-result.json";
      Json request={{"schema_version",1},{"current_pair_id",frame.meta.pair_id},
        {"input_manifest",pathUtf8(manifest)},{"calibration",pathUtf8(calibration)},
        {"raw_frames",pathUtf8(out/"frames.jsonl")},{"raw_detections",pathUtf8(out/"detections.jsonl")},
        {"current_frame",{{"meta",metaJson(frame.meta)},{"measurement",measured}}},
        {"output",pathUtf8(out/"online-kinematic-prefix")}};
      writeText(context,request.dump());
      std::string interpreter="python3",script=helper,input=pathUtf8(context),output=pathUtf8(result);
      char *args[]={interpreter.data(),script.data(),input.data(),output.data(),nullptr};
      pid_t child=0;
      int error=posix_spawnp(&child,interpreter.c_str(),nullptr,nullptr,args,environ);
      if(error)throw std::runtime_error("Kinematic helper spawn failed: "+std::to_string(error));
      int status=0;
      while(waitpid(child,&status,0)<0)if(errno!=EINTR)throw std::runtime_error("Kinematic helper wait failed");
      if(!WIFEXITED(status) || WEXITSTATUS(status))throw std::runtime_error("Kinematic helper failed");
      Json response=Json::parse(readText(result));
      state_["result"]=response;
      if(response.value("status",std::string())=="candidate") {
        if(response.at("max_source_pair_id").get<uint64_t>()>frame.meta.pair_id ||
           response.at("candidate").at("pair_id").get<uint64_t>()>frame.meta.pair_id)
          throw std::runtime_error("Kinematic probe attempted future-frame access");
        state_["candidate_seen"]=true;state_["candidate"]=response["candidate"];
        if(mode_=="stop") {
          handKinematicConfirmed=true;state_["stopped"]=true;
          state_["first_skipped_pair_id"]=frame.meta.pair_id+1;
        }
      }
    }catch(const std::exception &error){state_["error"]=error.what();}
    state_["wall_ms"]=std::chrono::duration<double,std::milli>(Clock::now()-begin).count();
    writeText(out/"hand-kinematic-stop.json",state_.dump(2));
  }
  const Json &state()const{return state_;}
};
}
