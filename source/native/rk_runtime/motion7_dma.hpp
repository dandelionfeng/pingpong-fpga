#pragma once
#include "pipeline/pipeline.hpp"
#include "inline_preprocess.hpp"
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <future>
#include <cstring>
#include <cstdlib>
// Private ABM7/AMR7 v1 adapter. Full source metadata stays attached on the host;
// echo fields and the per-eye reference are validated before B sees any mask.
class Motion7Dma {
 int user_=-1,tx_=-1,rx_=-1;void *bar_=MAP_FAILED,*send_=nullptr,*receive_=nullptr;
 std::array<pipeline::Meta,2> previous_{};bool first_=true;
 pipeline::CpuMotion reference_;
 uint32_t hardware_version_=1;int feature_mode_=0;std::array<cv::Mat,2> verify_previous_;
 static void put(uint8_t *p,uint64_t v,int n){for(int i=0;i<n;++i)p[i]=uint8_t(v>>(8*i));}
 static uint64_t get(const uint8_t*p,int n){uint64_t v=0;for(int i=0;i<n;++i)v|=uint64_t(p[i])<<(8*i);return v;}
public:
 static constexpr size_t input_bytes=640*360+32,output_bytes=640*360/8+48;
 size_t compared_pairs=0;
 Motion7Dma(){
  user_=open("/dev/ANLOGIC-PCI0_user",O_RDWR|O_SYNC);
  if(user_<0)throw std::runtime_error("Open physical motion7 BAR failed");
  bar_=mmap(nullptr,4096,PROT_READ|PROT_WRITE,MAP_SHARED,user_,0);
  if(bar_==MAP_FAILED)throw std::runtime_error("Map physical motion7 BAR failed");
  auto reg=[&](int offset)->volatile uint32_t&{return *reinterpret_cast<volatile uint32_t*>(static_cast<char*>(bar_)+offset);};
  hardware_version_=reg(0x34);feature_mode_=std::getenv("CHAIN_FPGA_FEATURE_MODE")?std::stoi(std::getenv("CHAIN_FPGA_FEATURE_MODE")):0;
  if(feature_mode_<0||feature_mode_>4)throw std::runtime_error("FPGA feature mode out of range");
  if(reg(0x30)!=0x37504d41 || (hardware_version_!=1&&hardware_version_!=2) || (hardware_version_==1&&feature_mode_!=0))throw std::runtime_error("Wrong FPGA algorithm version; requested feature mode is unavailable");
  reg(0x20)=0;std::atomic_thread_fence(std::memory_order_seq_cst);usleep(1000);
  reg(0x20)=1;std::atomic_thread_fence(std::memory_order_seq_cst);
  tx_=open("/dev/ANLOGIC-PCI0_h2c_0",O_WRONLY);rx_=open("/dev/ANLOGIC-PCI0_c2h_0",O_RDONLY);
  if(tx_<0||rx_<0||posix_memalign(&send_,4096,input_bytes)||posix_memalign(&receive_,4096,output_bytes))throw std::runtime_error("Open/allocate physical motion7 DMA failed");
 }
 pipeline::MotionResult process(const pipeline::FramePair &frame){
  using namespace pipeline;MotionResult result;result.meta=frame.meta;result.backend=hardware_version_==1?"fpga-seven-stage-abm7-v1-eram":"fpga-mask-features-v2-mode"+std::to_string(feature_mode_);
  if(frame.meta.config_version!="a-int-v1")throw std::runtime_error("ABM7 build is pinned to a-int-v1 / threshold 12");
  for(int e=0;e<2;++e){
   if(frame.search[e].type()!=CV_8UC1 || frame.search[e].size()!=cv::Size(640,360))throw std::runtime_error("Motion7 search image contract");
   if(!first_ && (frame.meta.pair_id<=previous_[e].pair_id || frame.meta.eye_timestamp_ns[e]<=previous_[e].eye_timestamp_ns[e]))throw std::runtime_error("Motion7 source sequence is not increasing");
   auto *send=static_cast<uint8_t*>(send_);std::memset(send,0,32);
   const uint32_t configTag=hardware_version_==1?0xa7010001:(0xa7020000|feature_mode_);
   put(send,0x374d4241,4);put(send+4,configTag,4);put(send+8,frame.meta.pair_id,8);
   put(send+16,frame.meta.eye_timestamp_ns[e],8);send[24]=e;send[25]=12;send[27]=feature_mode_;put(send+28,1024,4);
   for(int y=0;y<360;++y)std::memcpy(send+32+y*640,frame.search[e].ptr(y),640);
   auto reader=std::async(std::launch::async,[&]{return read(rx_,receive_,output_bytes);});
   auto written=write(tx_,send_,input_bytes);auto received=reader.get();
   if(written!=ssize_t(input_bytes)||received!=ssize_t(output_bytes))throw std::runtime_error("Physical motion7 DMA short/error transfer");
   const auto *response=static_cast<const uint8_t*>(receive_);
   uint64_t expected_reference=first_?0:previous_[e].pair_id;
   if(get(response,4)!=0x37524d41 || get(response+4,4)!=configTag || get(response+8,8)!=frame.meta.pair_id ||
      get(response+16,8)!=uint64_t(frame.meta.eye_timestamp_ns[e]) || get(response+24,8)!=expected_reference ||
      response[32]!=e || response[33]!=!first_ || response[34]!=feature_mode_ || response[35]!=12 ||
      get(response+36,2)!=640 || get(response+38,2)!=360 || get(response+40,4)!=28800 || get(response+44,4)!=hardware_version_)
       throw std::runtime_error("Physical motion7 response identity/reference/header mismatch");
   auto &eye=result.eyes[e];eye.reference_valid=!first_;eye.reference_id=expected_reference;
   eye.reference_timestamp_ns=first_?0:previous_[e].eye_timestamp_ns[e];
   eye.stages[6]=unpackMask(std::vector<uint8_t>(response+48,response+output_bytes),640,360);
  }
  if(std::getenv("CHAIN_VERIFY_FPGA_MASK")){
   auto expected=reference_.process(frame);if(!expected.valid)throw std::runtime_error(expected.error);
   for(int e=0;e<2;++e){auto wanted=field_preprocess::reference(expected.eyes[e].stages[0],expected.eyes[e].stages[1],verify_previous_[e],feature_mode_);
    if(packMask(wanted)!=packMask(result.eyes[e].stages[6]))throw std::runtime_error("Physical FPGA feature Mask differs from CPU reference at pair "+std::to_string(frame.meta.pair_id)+" eye "+std::to_string(e));
    verify_previous_[e]=expected.eyes[e].stages[0];}
   ++compared_pairs;
  }
  for(int e=0;e<2;++e)previous_[e]=frame.meta;first_=false;result.completion_ns=monotonicNs();return result;
 }
 pipeline::Json configuration()const{return {{"hardware_version",hardware_version_},{"mode",feature_mode_},{"threshold",12},{"weak",6},{"strong",18},{"energy_threshold",1024},
  {"reconstruction_steps",4},{"wire_payload","one-bit Mask; mode echoed in header and protected by BAR version"}};}
 ~Motion7Dma(){if(tx_>=0)close(tx_);if(rx_>=0)close(rx_);if(bar_!=MAP_FAILED)munmap(bar_,4096);if(user_>=0)close(user_);free(send_);free(receive_);}
};
