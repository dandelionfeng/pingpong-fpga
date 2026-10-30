cmake_minimum_required(VERSION 3.10)
project(rknn_v3_detect CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# On the board (AFH03 / RK3576J) these come from the Rockchip runtime package:
#   /usr/include/rknn_api.h  and  /usr/lib/librknnrt.so
# If your SDK keeps them elsewhere, pass -DRKNN_INC=... -DRKNN_LIB=...
set(RKNN_INC "/usr/include" CACHE PATH "dir containing rknn_api.h")
set(RKNN_LIB "/usr/lib" CACHE PATH "dir containing librknnrt.so")

find_library(RKNNRT NAMES rknnrt PATHS ${RKNN_LIB} NO_DEFAULT_PATH)
if(NOT RKNNRT)
  message(FATAL_ERROR "librknnrt.so not found in ${RKNN_LIB}; copy it from the board SDK")
endif()

add_executable(rknn_v3_detect rknn_v3_detect.cpp)
target_include_directories(rknn_v3_detect PRIVATE ${RKNN_INC})
target_link_libraries(rknn_v3_detect PRIVATE ${RKNNRT} pthread)
target_compile_options(rknn_v3_detect PRIVATE -O2 -Wall)
