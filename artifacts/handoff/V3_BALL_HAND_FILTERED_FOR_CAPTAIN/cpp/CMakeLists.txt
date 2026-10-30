cmake_minimum_required(VERSION 3.10)
project(rknn_v3_detect_filtered CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# On AFH03: /usr/include/rknn_api.h + /usr/lib/librknnrt.so (from the matching rknpu2 runtime).
set(RKNN_INC "/usr/include" CACHE PATH "dir containing rknn_api.h")
set(RKNN_LIB "/usr/lib" CACHE PATH "dir containing librknnrt.so")

# rknn_set_core_mask needs rknpu2 >= 1.6; build with -DUSE_CORE_MASK=OFF for older SDKs.
option(USE_CORE_MASK "use rknn_set_core_mask" ON)

find_library(RKNNRT NAMES rknnrt PATHS ${RKNN_LIB} NO_DEFAULT_PATH)
if(NOT RKNNRT)
  message(FATAL_ERROR "librknnrt.so not found in ${RKNN_LIB}; pass -DRKNN_LIB=...")
endif()

add_executable(rknn_v3_detect_filtered rknn_v3_detect_filtered.cpp)
target_include_directories(rknn_v3_detect_filtered PRIVATE ${RKNN_INC})
target_link_libraries(rknn_v3_detect_filtered PRIVATE ${RKNNRT} pthread)
target_compile_options(rknn_v3_detect_filtered PRIVATE -O2 -Wall)
if(NOT USE_CORE_MASK)
  target_compile_definitions(rknn_v3_detect_filtered PRIVATE NO_CORE_MASK)
endif()
