#include "runtime_session.hpp"
#include "threshold_policy.hpp"
#include "dfl_flat_decoder.hpp"
#include "output_layout_policy.hpp"
#include <rknn_api.h>
#include <array>
#include <opencv2/core.hpp>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <cstdio>
#include <cmath>
#include <cstdlib>
#include <arm_neon.h>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <mutex>
#include <numeric>
#include <stdexcept>

namespace c_actual {
std::vector<float> imageToNchw(const cv::Mat&, int);
namespace {
thread_local std::map<std::string,double> graph_timings;
std::vector<int64_t> canonical(const rknn_tensor_attr &attr) {
  std::vector<int64_t> result(attr.dims, attr.dims + attr.n_dims);
  if (attr.fmt == RKNN_TENSOR_NHWC && result.size() == 4)
    result = {result[0], result[3], result[1], result[2]};
  return result;
}
void require(int result, const char *operation) {
  if (result != RKNN_SUCC)
    throw std::runtime_error(std::string(operation) + " returned " + std::to_string(result));
}
bool version_at_least(const char *version, int want_major, int want_minor, int want_patch) {
  int major = 0, minor = 0, patch = 0;
  if (!version || std::sscanf(version, "%d.%d.%d", &major, &minor, &patch) != 3) return false;
  if (major != want_major) return major > want_major;
  if (minor != want_minor) return minor > want_minor;
  return patch >= want_patch;
}
}
struct RknnSharedContext {
  rknn_context context = 0;
  rknn_tensor_attr input{}, native_input_attr{}, output{};
  std::vector<rknn_tensor_attr> heads;
  bool flat_dfl=false;
  FlatDflLayout flat_layout;
  std::array<int8_t,256> input_lut{};
  bool input_xor=false;
  std::array<std::array<float,256>,6> output_lut{};
  int head_classes=0,input_side=0;
  size_t anchors=0;
  std::mutex mutex;
  std::vector<float> native_input;
  std::vector<int8_t> quant_input;
  rknn_tensor_mem *input_mem=nullptr;
  std::string model_name;
  ~RknnSharedContext() {
    if(context && input_mem)rknn_destroy_mem(context,input_mem);
    if(context)rknn_destroy(context);
  }
};
bool OrtSession::load(const std::string &path, bool use_cuda, int, std::string *error) {
  try {
    if (use_cuda) throw std::runtime_error("CUDA is not a board RKNN execution mode");
    static std::mutex cache_mutex;
    static std::map<std::string, std::weak_ptr<RknnSharedContext>> cache;
    std::lock_guard<std::mutex> cache_lock(cache_mutex);
    static std::map<std::string,size_t> context_numbers;
    auto prototype=cache[path].lock();
    bool duplicate=std::getenv("C_OPT_DUP_CONTEXT") && std::string(std::getenv("C_OPT_DUP_CONTEXT"))=="1";
    auto shared=duplicate?std::shared_ptr<RknnSharedContext>{}:prototype;
    if (!shared) {
      std::ifstream stream(path, std::ios::binary | std::ios::ate);
      if (!stream) throw std::runtime_error("Cannot open RKNN model: " + path);
      const auto size = stream.tellg();
      if (size <= 0 || size > 256 * 1024 * 1024)
        throw std::runtime_error("Invalid RKNN model size");
      std::vector<char> bytes(static_cast<size_t>(size));
      stream.seekg(0);
      if (!stream.read(bytes.data(), size)) throw std::runtime_error("Cannot read RKNN model");
      shared = std::make_shared<RknnSharedContext>();
      shared->model_name = path.substr(path.find_last_of("/\\") + 1);
      if(duplicate && prototype)
        require(rknn_dup_context(&prototype->context,&shared->context),"duplicate context with shared weights");
      else
      require(rknn_init(&shared->context, bytes.data(), static_cast<uint32_t>(bytes.size()), 0, nullptr), "rknn_init");
      auto core=RKNN_NPU_CORE_ALL;
      if(const char *v=std::getenv("C_OPT_CORE")) {
        if(std::string(v)=="split")core=(context_numbers[path]++%2)?RKNN_NPU_CORE_1:RKNN_NPU_CORE_0;
        else if(std::string(v)=="0")core=RKNN_NPU_CORE_0;
        else if(std::string(v)=="1")core=RKNN_NPU_CORE_1;
      }
      require(rknn_set_core_mask(shared->context,core), "rknn_set_core_mask");
      rknn_input_output_num count{};
      require(rknn_query(shared->context, RKNN_QUERY_IN_OUT_NUM, &count, sizeof(count)), "query in/out");
      OutputMode output_mode;
      std::string output_mode_error;
      if (count.n_input != 1 || !select_output_mode(count.n_output, &output_mode, &output_mode_error))
        throw std::runtime_error(output_mode_error.empty() ? "Expected exactly one input" : output_mode_error);
      require(rknn_query(shared->context, RKNN_QUERY_INPUT_ATTR, &shared->input, sizeof(shared->input)), "query input");
      require(rknn_query(shared->context, RKNN_QUERY_NATIVE_INPUT_ATTR, &shared->native_input_attr, sizeof(shared->native_input_attr)), "query native input");
      require(rknn_query(shared->context, RKNN_QUERY_OUTPUT_ATTR, &shared->output, sizeof(shared->output)), "query output");
      if (output_mode == OutputMode::kRawHeads) {
        auto input_dims=canonical(shared->input);
        if(input_dims.size()!=4 || input_dims[0]!=1 || input_dims[1]!=3 || input_dims[2]!=input_dims[3] || input_dims[2]%32)
          throw std::runtime_error("Raw-head square input contract mismatch");
        shared->input_side=int(input_dims[2]);
        shared->heads.resize(6);
        for (uint32_t i=0;i<6;++i) {
          auto &attr=shared->heads[i]; attr.index=i;
          require(rknn_query(shared->context,RKNN_QUERY_OUTPUT_ATTR,&attr,sizeof(attr)),"query head");
          auto dims=canonical(attr);
          int side=(shared->input_side/8)/(1<<(i/2));
          if(i==1 && dims.size()==4) shared->head_classes=int(dims[1]);
          int nc=i%2 ? (i==1 && dims.size()==4 ? int(dims[1]):shared->head_classes):64;
          if ((i%2 && nc!=1 && nc!=3) || dims!=std::vector<int64_t>{1,nc,side,side} || attr.fmt!=RKNN_TENSOR_NCHW)
            throw std::runtime_error("YOLO raw head shape/layout mismatch");
          if(i%2) shared->anchors+=side*side;
        }
      } else if (output_mode == OutputMode::kFlatDfl) {
        auto input_dims=canonical(shared->input);
        if(input_dims.size()!=4 || input_dims[0]!=1 || input_dims[1]!=3 ||
           input_dims[2]!=960 || input_dims[3]!=960)
          throw std::runtime_error("8-output DFL model requires a [1,3,960,960] input");
        shared->input_side=960;
        std::vector<std::vector<int64_t>> shapes;
        shapes.reserve(8);
        for (uint32_t i=0;i<8;++i) {
          rknn_tensor_attr attr{};
          attr.index=i;
          require(rknn_query(shared->context,RKNN_QUERY_OUTPUT_ATTR,&attr,sizeof(attr)),"query DFL output");
          shapes.push_back(canonical(attr));
        }
        std::string layout_error;
        if (!identify_flat_dfl(shapes, &shared->flat_layout, &layout_error))
          throw std::runtime_error("8-output DFL layout rejected: " + layout_error);
        shared->flat_dfl=true;
        shared->head_classes=shared->flat_layout.classes;
        shared->anchors=shared->flat_layout.anchors;
      }
      if (shared->input.n_dims != 4 || shared->output.n_dims < 3 || shared->output.n_dims > 4)
        throw std::runtime_error("Unsupported RKNN tensor dimensions");
      rknn_sdk_version sdk{};
      require(rknn_query(shared->context, RKNN_QUERY_SDK_VERSION, &sdk, sizeof(sdk)), "query SDK version");
      const bool runtime_23 = std::string(sdk.api_version).rfind("2.3.0", 0) == 0;
      const bool runtime_25 = version_at_least(sdk.api_version, 2, 5, 0);
      if (shared->flat_dfl && !runtime_25)
        throw std::runtime_error(std::string("8-output DFL model requires RKNN runtime >= 2.5.0; found ") +
                                 sdk.api_version + ". Do not bypass this check; upgrade the board runtime.");
      if (!shared->flat_dfl && !runtime_23 && !runtime_25)
        throw std::runtime_error("This deployment expects RKNN runtime 2.3.0 or >=2.5.0; found " +
                                 std::string(sdk.api_version));
      std::cerr << "RKNN_PHYSICAL_CONTEXT model=" << path << " runtime=" << sdk.api_version
                << " driver=" << sdk.drv_version << " input=";
      for (auto d:canonical(shared->input)) std::cerr << d << ',';
      std::cerr << " output=";
      for (auto d:canonical(shared->output)) std::cerr << d << ',';
      std::cerr << " native_input_type=" << shared->native_input_attr.type
                << " native_input_fmt=" << shared->native_input_attr.fmt
                << " native_input_bytes=" << shared->native_input_attr.size_with_stride;
      std::cerr << '\n';
      if(shared->input.type==RKNN_TENSOR_INT8 && shared->input.scale>0) {
        std::array<uint8_t,256> ramp{};
        std::array<float,256> normalized{};
        for(int i=0;i<256;++i)ramp[i]=static_cast<uint8_t>(i);
        cv::Mat(1,256,CV_8U,ramp.data()).convertTo(cv::Mat(1,256,CV_32F,normalized.data()),CV_32F,1.0/255.0);
        const float inverse=1.f/shared->input.scale;
        for(int i=0;i<256;i+=8) {
          auto a=vcvtq_s32_f32(vaddq_f32(vmulq_n_f32(vld1q_f32(normalized.data()+i),inverse),vdupq_n_f32(.5f)));
          auto b=vcvtq_s32_f32(vaddq_f32(vmulq_n_f32(vld1q_f32(normalized.data()+i+4),inverse),vdupq_n_f32(.5f)));
          a=vaddq_s32(a,vdupq_n_s32(shared->input.zp));b=vaddq_s32(b,vdupq_n_s32(shared->input.zp));
          vst1_s8(shared->input_lut.data()+i,vqmovn_s16(vcombine_s16(vqmovn_s32(a),vqmovn_s32(b))));
        }
        shared->input_xor=true;
        for(int i=0;i<256;++i)
          if(shared->input_lut[i]!=i-128)shared->input_xor=false;
        std::cerr<<"INPUT_NATIVE_XOR model="<<shared->model_name<<" exact_all_256="<<shared->input_xor<<'\n';
      }
      for(size_t h=0;h<shared->heads.size();++h)for(int i=0;i<256;++i) {
        int q=i<128?i:i-256;
        const float scale=shared->heads[h].scale;
        // Match this fixed SDK's vector box-head and scalar class-head rounding.
        // C_RKNN_VERIFY_NATIVE checks every element against SDK float output.
        shared->output_lut[h][i]=h%2 ? float(q-shared->heads[h].zp)*scale :
          std::fma(float(q),scale,-float(shared->heads[h].zp)*scale);
      }
      if(std::getenv("C_OPT_ZINPUT") && std::string(std::getenv("C_OPT_ZINPUT"))=="1") {
        auto native=shared->native_input_attr;
        if(native.type!=RKNN_TENSOR_INT8 || native.fmt!=RKNN_TENSOR_NHWC || native.size_with_stride!=native.n_elems)
          throw std::runtime_error("Zero-copy input native stride/type mismatch");
        shared->input_mem=rknn_create_mem(shared->context,native.size_with_stride);
        if(!shared->input_mem)throw std::runtime_error("NPU input allocation failed");
        native.pass_through=1;
        require(rknn_set_io_mem(shared->context,shared->input_mem,&native),"bind input memory");
      }
      cache[path] = shared;
    }
    input_name_ = shared->input.name;
    output_name_ = shared->output.name;
    session_ = std::move(shared);
    return true;
  } catch (const std::exception &e) {
    if (error) *error = e.what();
    session_.reset();
    return false;
  }
}
std::vector<int64_t> OrtSession::inputShape() const { return session_ ? canonical(session_->input) : std::vector<int64_t>{}; }
std::vector<int64_t> OrtSession::outputShape() const {
  if (!session_) return {};
  if (session_->flat_dfl)
    return {1, 4 + session_->flat_layout.classes, static_cast<int64_t>(session_->flat_layout.anchors)};
  return session_->heads.empty() ? canonical(session_->output)
                                 : std::vector<int64_t>{1, 4 + session_->head_classes,
                                                        static_cast<int64_t>(session_->anchors)};
}
bool OrtSession::run(const std::vector<float> &input,const std::vector<int64_t>& shape,
                     std::vector<float>* output,std::vector<int64_t>* output_shape,std::string* error,
                     float base_conf) {
  return runImpl(input,shape,nullptr,0,output,output_shape,error,base_conf);
}
bool OrtSession::runImage(const uint8_t* bgr,size_t bytes,const std::vector<int64_t>& shape,
                         std::vector<float>* output,std::vector<int64_t>* output_shape,std::string* error) {
  std::vector<float> reference;
  if(std::getenv("C_RKNN_VERIFY_NATIVE") && shape.size()==4) {
    cv::Mat boxed(static_cast<int>(shape[2]),static_cast<int>(shape[3]),CV_8UC3,const_cast<uint8_t*>(bgr));
    reference=imageToNchw(boxed,int(shape[2]));
  }
  return runImpl(reference,shape,bgr,bytes,output,output_shape,error,-1.0f);
}
bool OrtSession::runImpl(const std::vector<float> &input, const std::vector<int64_t> &shape,
                        const uint8_t* image,size_t image_bytes,
                        std::vector<float> *output, std::vector<int64_t> *output_shape, std::string *error,
                        float base_conf) {
  try {
    auto begin=std::chrono::steady_clock::now();
    if (!session_ || shape != inputShape() || shape.size() != 4 || shape[0] != 1)
      throw std::runtime_error("RKNN input contract mismatch");
    const size_t count = std::accumulate(shape.begin(), shape.end(), size_t{1}, std::multiplies<size_t>());
    if ((image && image_bytes!=count) || (!image && input.size()!=count))
      throw std::runtime_error("RKNN input element count mismatch");
    std::lock_guard<std::mutex> lock(session_->mutex);
    auto phase=std::chrono::steady_clock::now();
    auto checkpoint=[&](const char *name){auto now=std::chrono::steady_clock::now();double elapsed=std::chrono::duration<double,std::milli>(now-phase).count();graph_timings[name]=elapsed;graph_timings[session_->model_name+"/"+name]=elapsed;phase=now;};
    const size_t channels = static_cast<size_t>(shape[1]);
    const size_t plane = static_cast<size_t>(shape[2] * shape[3]);
    rknn_input item{};
    item.index = 0;
    item.fmt = RKNN_TENSOR_NHWC;
    item.pass_through = 0;
    bool optimized=!std::getenv("C_RKNN_BASELINE_IO");
    // Validate the candidate floor even in full-DFL mode so a bad config cannot
    // silently run. -1 means "no early filtering" for BallTrack/other callers.
    CandidateThreshold candidate;
    std::string candidate_error;
    if (!candidate_threshold(base_conf, &candidate, &candidate_error))
      throw std::runtime_error(candidate_error);
    const bool full_dfl = std::getenv("C_RKNN_FULL_DFL") != nullptr;
    const bool early_filter = optimized && !full_dfl;
    const auto &attr=session_->input;
    if(image) {
      if(attr.type!=RKNN_TENSOR_INT8 || attr.qnt_type!=RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC ||
         attr.fmt!=RKNN_TENSOR_NHWC || attr.size_with_stride!=count || attr.scale<=0)
        throw std::runtime_error("Native image input requires verified dense INT8 NHWC");
      auto &native=session_->quant_input;
      if(!session_->input_mem)native.resize(count);
      auto *destination=session_->input_mem?static_cast<int8_t*>(session_->input_mem->virt_addr):native.data();
      if(channels!=3 || image_bytes!=count)throw std::runtime_error("Native image contract mismatch");
      const auto &lut=session_->input_lut;
      size_t pixel=0;
      if(session_->input_xor) {
        const uint8x8_t sign=vdup_n_u8(128);
        for(;pixel+8<=plane;pixel+=8) {
          auto bgr=vld3_u8(image+3*pixel);
          uint8x8x3_t rgb{{veor_u8(bgr.val[2],sign),veor_u8(bgr.val[1],sign),veor_u8(bgr.val[0],sign)}};
          vst3_u8(reinterpret_cast<uint8_t*>(destination)+3*pixel,rgb);
        }
      }
      for(;pixel<plane;++pixel) {
        destination[3*pixel]=lut[image[3*pixel+2]];
        destination[3*pixel+1]=lut[image[3*pixel+1]];
        destination[3*pixel+2]=lut[image[3*pixel]];
      }
      if(std::getenv("C_RKNN_VERIFY_NATIVE")) {
        if(input.size()!=count)throw std::runtime_error("Verification tensor missing");
        auto reference=[&](){
      std::vector<int8_t> native(count);
      const float inverse=1.f/attr.scale;
      bool gray3=channels==3 && session_->heads.size()==6 &&
        !std::memcmp(input.data(),input.data()+plane,plane*sizeof(float)) &&
        !std::memcmp(input.data(),input.data()+2*plane,plane*sizeof(float));
      if(gray3) {
        size_t pixel=0;
        for(;pixel+8<=plane;pixel+=8) {
          auto a=vcvtq_s32_f32(vaddq_f32(vmulq_n_f32(vld1q_f32(input.data()+pixel),inverse),vdupq_n_f32(.5f)));
          auto b=vcvtq_s32_f32(vaddq_f32(vmulq_n_f32(vld1q_f32(input.data()+pixel+4),inverse),vdupq_n_f32(.5f)));
          a=vaddq_s32(a,vdupq_n_s32(attr.zp));b=vaddq_s32(b,vdupq_n_s32(attr.zp));
          int8x8_t values=vqmovn_s16(vcombine_s16(vqmovn_s32(a),vqmovn_s32(b)));
          int8x8x3_t triplet{{values,values,values}};
          vst3_s8(native.data()+3*pixel,triplet);
        }
        for(;pixel<plane;++pixel) {
          // Unified inputs originate from uint8 GRAY8/255: quantization has no half ties.
          int q=static_cast<int>(input[pixel]*inverse+.5f)+attr.zp;
          auto value=static_cast<int8_t>(std::clamp(q,-128,127));
          native[3*pixel]=value;native[3*pixel+1]=value;native[3*pixel+2]=value;
        }
      } else {
        for(size_t pixel=0;pixel<plane;++pixel)
          for(size_t c=0;c<channels;++c) {
            int q=static_cast<int>(std::round(input[c*plane+pixel]*inverse))+attr.zp;
            native[pixel*channels+c]=static_cast<int8_t>(std::clamp(q,-128,127));
          }
      }

          return native;
        }();
        if(std::memcmp(reference.data(),destination,count))throw std::runtime_error("Native input differs from frozen INT8 bytes");
        graph_timings[session_->model_name+"/native_input_bytes_verified"]=1.;
      }
      item.buf=destination;item.size=count;item.type=RKNN_TENSOR_INT8;item.pass_through=1;
    } else if(optimized && attr.type==RKNN_TENSOR_INT8 && attr.qnt_type==RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC &&
        attr.fmt==RKNN_TENSOR_NHWC && attr.size_with_stride==count && attr.scale>0) {
      auto &native=session_->quant_input;native.resize(count);
      const float inverse=1.f/attr.scale;
      bool gray3=channels==3 && session_->heads.size()==6 &&
        !std::memcmp(input.data(),input.data()+plane,plane*sizeof(float)) &&
        !std::memcmp(input.data(),input.data()+2*plane,plane*sizeof(float));
      if(gray3) {
        size_t pixel=0;
        for(;pixel+8<=plane;pixel+=8) {
          auto a=vcvtq_s32_f32(vaddq_f32(vmulq_n_f32(vld1q_f32(input.data()+pixel),inverse),vdupq_n_f32(.5f)));
          auto b=vcvtq_s32_f32(vaddq_f32(vmulq_n_f32(vld1q_f32(input.data()+pixel+4),inverse),vdupq_n_f32(.5f)));
          a=vaddq_s32(a,vdupq_n_s32(attr.zp));b=vaddq_s32(b,vdupq_n_s32(attr.zp));
          int8x8_t values=vqmovn_s16(vcombine_s16(vqmovn_s32(a),vqmovn_s32(b)));
          int8x8x3_t triplet{{values,values,values}};
          vst3_s8(native.data()+3*pixel,triplet);
        }
        for(;pixel<plane;++pixel) {
          // Unified inputs originate from uint8 GRAY8/255: quantization has no half ties.
          int q=static_cast<int>(input[pixel]*inverse+.5f)+attr.zp;
          auto value=static_cast<int8_t>(std::clamp(q,-128,127));
          native[3*pixel]=value;native[3*pixel+1]=value;native[3*pixel+2]=value;
        }
      } else {
        for(size_t pixel=0;pixel<plane;++pixel)
          for(size_t c=0;c<channels;++c) {
            int q=static_cast<int>(std::round(input[c*plane+pixel]*inverse))+attr.zp;
            native[pixel*channels+c]=static_cast<int8_t>(std::clamp(q,-128,127));
          }
      }
      item.buf=native.data();item.size=native.size();item.type=RKNN_TENSOR_INT8;item.pass_through=1;
    } else if(optimized && session_->native_input_attr.type==RKNN_TENSOR_FLOAT16 &&
        session_->native_input_attr.fmt==RKNN_TENSOR_NHWC &&
        session_->native_input_attr.size_with_stride==count*2 && channels==3) {
      // Match the runtime's own float32 -> float16 conversion at its native input.
      // Reuse the scratch storage (overallocated) without introducing quantization.
      auto &native=session_->quant_input;native.resize(count*2);
      auto *half=reinterpret_cast<__fp16*>(native.data());
      bool gray3=!std::memcmp(input.data(),input.data()+plane,plane*sizeof(float)) &&
        !std::memcmp(input.data(),input.data()+2*plane,plane*sizeof(float));
      if(gray3) {
        size_t pixel=0;
        for(;pixel+4<=plane;pixel+=4) {
          float16x4_t values=vcvt_f16_f32(vld1q_f32(input.data()+pixel));
          float16x4x3_t triplet{{values,values,values}};
          vst3_f16(half+3*pixel,triplet);
        }
        for(;pixel<plane;++pixel)half[3*pixel]=half[3*pixel+1]=half[3*pixel+2]=static_cast<__fp16>(input[pixel]);
      } else for(size_t pixel=0;pixel<plane;++pixel)
        for(size_t c=0;c<channels;++c)half[pixel*channels+c]=static_cast<__fp16>(input[c*plane+pixel]);
      item.buf=native.data();item.size=native.size();item.type=RKNN_TENSOR_FLOAT16;item.pass_through=1;
    } else {
      auto &native=session_->native_input;native.resize(count);
      for(size_t pixel=0;pixel<plane;++pixel)
        for(size_t c=0;c<channels;++c) native[pixel*channels+c]=input[c*plane+pixel];
      item.buf=native.data();item.size=native.size()*sizeof(float);item.type=RKNN_TENSOR_FLOAT32;
    }
    checkpoint("input_layout_ms");
    if(session_->input_mem) {
      if(item.type!=RKNN_TENSOR_INT8 || item.size!=session_->input_mem->size)
        throw std::runtime_error("Bound input memory contract mismatch");
      if(item.buf!=session_->input_mem->virt_addr)std::memcpy(session_->input_mem->virt_addr,item.buf,item.size);
      require(rknn_mem_sync(session_->context,session_->input_mem,RKNN_MEMORY_SYNC_TO_DEVICE),"sync bound input");
    } else require(rknn_inputs_set(session_->context, 1, &item), "rknn_inputs_set");
    checkpoint("rknn_inputs_set_ms");
    require(rknn_run(session_->context, nullptr), "rknn_run");
    checkpoint("rknn_run_ms");
    if (session_->flat_dfl) {
      rknn_output results[8]{};
      for (uint32_t i=0;i<8;++i) {
        results[i].index=i;
        // Ask the runtime to dequantise/converts every output exactly once.
        // The delivered INT8 model already reports float32 outputs; a second
        // manual (q-zp)*scale pass would corrupt them.
        results[i].want_float=1;
      }
      require(rknn_outputs_get(session_->context,8,results,nullptr),"get eight DFL outputs");
      struct FlatRelease { rknn_context c; rknn_output *p; ~FlatRelease(){rknn_outputs_release(c,8,p);} } release{session_->context,results};
      const auto &layout=session_->flat_layout;
      const auto &dfl=results[layout.dfl_index];
      const auto &cls=results[layout.class_index];
      if (!dfl.buf || !cls.buf ||
          dfl.size!=64*layout.anchors*sizeof(float) ||
          cls.size!=static_cast<size_t>(layout.classes)*layout.anchors*sizeof(float))
        throw std::runtime_error("8-output DFL output buffer mismatch");
      output->assign((4+layout.classes)*layout.anchors,0.f);
      decode_flat_dfl(static_cast<const float*>(dfl.buf),
                      static_cast<const float*>(cls.buf), layout, candidate,
                      early_filter, output->data());
      *output_shape={1,4+layout.classes,static_cast<int64_t>(layout.anchors)};
      graph_timings[session_->model_name+"/flat_dfl_layout"]=1.;
      checkpoint("cpu_dfl_ms");
    } else if (!session_->heads.empty()) {
      rknn_output results[6]{};
      const bool quant_output=(!std::getenv("C_OPT_QOUTPUT") || std::string(std::getenv("C_OPT_QOUTPUT"))!="0") &&
        std::all_of(session_->heads.begin(),session_->heads.end(),[](const auto &a){return a.type==RKNN_TENSOR_INT8 && a.qnt_type==RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC;});
      for(uint32_t i=0;i<6;++i) {results[i].index=i;results[i].want_float=quant_output?0:1;}
      require(rknn_outputs_get(session_->context,6,results,nullptr),"get six heads");
      checkpoint("rknn_outputs_get_ms");
      struct HeadRelease { rknn_context c; rknn_output *p; ~HeadRelease(){rknn_outputs_release(c,6,p);} } release{session_->context,results};
      if(quant_output && std::getenv("C_RKNN_VERIFY_NATIVE")) {
        std::array<std::vector<uint8_t>,6> saved;
        for(size_t h=0;h<6;++h) {
          auto *p=static_cast<const uint8_t*>(results[h].buf);
          saved[h].assign(p,p+results[h].size);
        }
        rknn_output reference[6]{};
        for(uint32_t h=0;h<6;++h){reference[h].index=h;reference[h].want_float=1;}
        require(rknn_outputs_get(session_->context,6,reference,nullptr),"get reference float heads");
        HeadRelease ref_release{session_->context,reference};
        for(size_t h=0;h<6;++h) {
          const auto *q=saved[h].data();
          const auto *f=static_cast<const float*>(reference[h].buf);
          if(!q || !f || reference[h].size!=session_->heads[h].n_elems*sizeof(float))
            throw std::runtime_error("Reference output contract mismatch");
          for(size_t i=0;i<session_->heads[h].n_elems;++i) {
            float v=session_->output_lut[h][q[i]];
            if(std::memcmp(&v,f+i,sizeof(float))) {
              const int qi=q[i]<128?q[i]:int(q[i])-256;
              std::cerr << "QOUTPUT_MISMATCH h="<<h<<" i="<<i<<" q="<<qi<<" zp="<<session_->heads[h].zp<<std::hexfloat<<" scale="<<session_->heads[h].scale<<" predicted="<<v<<" reference="<<f[i]<<" subfirst="<<float(qi-session_->heads[h].zp)*session_->heads[h].scale<<" fma="<<std::fma(float(qi),session_->heads[h].scale,-float(session_->heads[h].zp)*session_->heads[h].scale)<<std::defaultfloat<<" bytes="<<results[h].size<<" elems="<<session_->heads[h].n_elems<<'\n';
              throw std::runtime_error("Quantized output differs from runtime float bytes: head "+std::to_string(h)+" index "+std::to_string(i));
            }
          }
        }
        graph_timings[session_->model_name+"/all_six_output_heads_bytes_verified"]=1.;
      }
      const int classes=session_->head_classes;
      const size_t anchors=session_->anchors;
      output->assign((4+classes)*anchors,0.f);
      size_t offset=0;
      for(int scale=0;scale<3;++scale) {
        int side=(session_->input_side/8)/(1<<scale), plane=side*side, stride=8<<scale;
        for(int branch=0;branch<2;++branch)
          if(!results[2*scale+branch].buf || results[2*scale+branch].size!=session_->heads[2*scale+branch].n_elems*(quant_output?sizeof(int8_t):sizeof(float)))
            throw std::runtime_error("Head output buffer mismatch");
        const float *box=static_cast<const float*>(results[2*scale].buf);
        const float *cls=static_cast<const float*>(results[2*scale+1].buf);
        const auto *qbox=static_cast<const uint8_t*>(results[2*scale].buf);
        const auto *qcls=static_cast<const uint8_t*>(results[2*scale+1].buf);
        auto boxValue=[&](size_t i){return quant_output?session_->output_lut[2*scale][qbox[i]]:box[i];};
        auto clsValue=[&](size_t i){return quant_output?session_->output_lut[2*scale+1][qcls[i]]:cls[i];};
        for(int pixel=0;pixel<plane;++pixel) {
          size_t j=offset+pixel;
          float maximum_logit=clsValue(pixel);
          for(int c=1;c<classes;++c) maximum_logit=std::max(maximum_logit,clsValue(c*plane+pixel));
          // Candidate floor comes from the caller's config base_conf. The
          // equivalent logit is log(p/(1-p)); 0 skips nothing and 1 skips all.
          // C_RKNN_FULL_DFL bypasses this early skip, while YoloDetector still
          // applies the same confidence threshold after full decoding.
          if(candidate_should_skip(maximum_logit,candidate,early_filter)) continue;
          float confidence=0;
          for(int c=0;c<classes;++c) {
            float score=1.f/(1.f+std::exp(-clsValue(c*plane+pixel)));
            (*output)[(4+c)*anchors+j]=score;confidence=std::max(confidence,score);
          }
          (void)confidence;  // kept for parity/diagnostics; filtering is by logit above.
          float d[4];
          for(int k=0;k<4;++k) {
            float maximum=-INFINITY;
            for(int bin=0;bin<16;++bin) maximum=std::max(maximum,boxValue((k*16+bin)*plane+pixel));
            float sum=0,weighted=0;
            for(int bin=0;bin<16;++bin) {float v=std::exp(boxValue((k*16+bin)*plane+pixel)-maximum);sum+=v;weighted+=bin*v;}
            d[k]=weighted/sum;
          }
          float x=pixel%side+.5f,y=pixel/side+.5f;
          (*output)[j]=(x+(d[2]-d[0])*.5f)*stride;
          (*output)[anchors+j]=(y+(d[3]-d[1])*.5f)*stride;
          (*output)[2*anchors+j]=(d[0]+d[2])*stride;
          (*output)[3*anchors+j]=(d[1]+d[3])*stride;
        }
        offset+=plane;
      }
      *output_shape={1,4+classes,static_cast<int64_t>(anchors)};
      checkpoint("cpu_dfl_ms");
    } else {
    rknn_output result{};
    result.index = 0;
    result.want_float = 1;
    require(rknn_outputs_get(session_->context, 1, &result, nullptr), "rknn_outputs_get");
    struct Release {
      rknn_context context;
      rknn_output *output;
      ~Release() { rknn_outputs_release(context, 1, output); }
    } release{session_->context, &result};
    if (!result.buf || result.size != session_->output.n_elems * sizeof(float))
      throw std::runtime_error("Unexpected RKNN output buffer size");
    auto ptr = static_cast<const float *>(result.buf);
    output->assign(ptr, ptr + session_->output.n_elems);
    *output_shape = outputShape();
    }
    graph_timings[session_->model_name] = std::chrono::duration<double,std::milli>(
        std::chrono::steady_clock::now()-begin).count();
    return true;
  } catch (const std::exception &e) {
    if (error) *error = e.what();
    return false;
  }
}
void recordDiagnosticTiming(const std::string &key, double value) { graph_timings[key]=value; }
void resetRuntimeTimings() { graph_timings.clear(); }
std::map<std::string,double> lastRuntimeTimings() { return graph_timings; }
}
