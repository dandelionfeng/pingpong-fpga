cmake_minimum_required(VERSION 3.10)
project(rknn_v3_detect CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# On the board (AFH03 / RK3576J) these come from the Rockchip runtime package:
#   /usr/include/rknn_api.h  and  /usr/lib/librknnrt.so
# Override with -DRKNN_INC=... -DRKNN_LIB=... if your SDK puts them elsewhere.
set(RKNN_INC "/usr/include" CACHE PATH "dir containing rknn_api.h")
set(RKNN_LIB "/usr/lib" CACHE PATH "dir containing librknnrt.so")

# Older rknn_api.h (<1.6) has no rknn_set_core_mask; build with -DUSE_CORE_MASK=OFF then.
option(USE_CORE_MASK "use rknn_set_core_mask (needs rknpu2 >= 1.6)" ON)

find_library(RKNNRT NAMES rknnrt PATHS ${RKNN_LIB} NO_DEFAULT_PATH)
if(NOT RKNNRT)
  message(FATAL_ERROR "librknnrt.so not found in ${RKNN_LIB}; copy it from the board SDK "
                      "(rknpu2/runtime/Linux/librknn_api/aarch64/) or pass -DRKNN_LIB=...")
endif()

add_executable(rknn_v3_detect rknn_v3_detect.cpp)
target_include_directories(rknn_v3_detect PRIVATE ${RKNN_INC})
target_link_libraries(rknn_v3_detect PRIVATE ${RKNNRT} pthread)
target_compile_options(rknn_v3_detect PRIVATE -O2 -Wall)
if(NOT USE_CORE_MASK)
  target_compile_definitions(rknn_v3_detect PRIVATE NO_CORE_MASK)
  message(STATUS "core_mask API disabled (NO_CORE_MASK); runtime will use AUTO")
endif()
