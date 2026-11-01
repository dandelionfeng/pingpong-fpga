# C actual-model perception module: gray3 C++17 ONNX Runtime inference engine.
#
# This module is deliberately standalone (like ball_measurement/): it builds the
# captain-facing engine + CLI with only ONNX Runtime and OpenCV. The in-tree
# pipeline targets (which need a full cv::Mat/JSON toolchain) are unaffected.
#
# Dependencies are located by CMAKE_PREFIX_PATH or the -D options below; the
# repo-local third_party/ cache is searched last. Nothing here downloads at
# configure time.

cmake_minimum_required(VERSION 3.20)
project(c_actual LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# The DetectorBackend bridge also needs the pc_pipeline headers (Json/Meta), so it
# is opt-in. Point C_ACTUAL_PIPELINE_INCLUDE at software/pc_pipeline/include to
# build it.
option(C_ACTUAL_BUILD_PIPELINE_BRIDGE "Build the DetectorBackend bridge" OFF)
set(C_ACTUAL_PIPELINE_INCLUDE "${CMAKE_CURRENT_SOURCE_DIR}/../../include"
    CACHE PATH "software/pc_pipeline/include")
set(C_ACTUAL_JSON_INCLUDE "" CACHE PATH "Optional nlohmann/json include directory for standalone bridge builds")

# ---------------------------------------------------------------- dependencies
# ONNX Runtime
set(C_ACTUAL_ONNXRUNTIME_ROOT "" CACHE PATH "ONNX Runtime root (contains include/ and lib/)")
set(C_ACTUAL_OPENCV_ROOT "" CACHE PATH "OpenCV root (contains build/include and build/x64/*)")

function(c_actual_find_onnxruntime)
  set(_candidates)
  if(C_ACTUAL_ONNXRUNTIME_ROOT)
    list(APPEND _candidates "${C_ACTUAL_ONNXRUNTIME_ROOT}")
  endif()
  if(DEFINED ENV{ONNXRUNTIME_ROOT})
    list(APPEND _candidates "$ENV{ONNXRUNTIME_ROOT}")
  endif()
  file(GLOB _local "${CMAKE_CURRENT_SOURCE_DIR}/../../../third_party/onnxruntime-win-x64-*")
  list(APPEND _candidates ${_local})

  foreach(_root IN LISTS _candidates)
    if(EXISTS "${_root}/include/onnxruntime_cxx_api.h")
      set(C_ACTUAL_ONNXRUNTIME_ROOT "${_root}" PARENT_SCOPE)
      return()
    endif()
  endforeach()
  message(FATAL_ERROR
    "ONNX Runtime not found. Pass -DC_ACTUAL_ONNXRUNTIME_ROOT=<dir> or set ONNXRUNTIME_ROOT. "
    "Expected <dir>/include/onnxruntime_cxx_api.h")
endfunction()

function(c_actual_find_opencv)
  # The official Windows package ships a CMake package config, so point
  # find_package at it when we discovered a manual layout. That gives us a
  # proper imported target (including the version-suffixed world library and its
  # include dirs) instead of hand-rolled link directories.
  set(_candidates)
  if(C_ACTUAL_OPENCV_ROOT)
    list(APPEND _candidates "${C_ACTUAL_OPENCV_ROOT}")
  endif()
  if(DEFINED ENV{OpenCV_DIR})
    get_filename_component(_env_root "$ENV{OpenCV_DIR}/../../.." ABSOLUTE)
    list(APPEND _candidates "${_env_root}")
  endif()
  file(GLOB _local "${CMAKE_CURRENT_SOURCE_DIR}/../../../third_party/opencv*")
  list(APPEND _candidates ${_local})

  foreach(_root IN LISTS _candidates)
    file(GLOB _configs "${_root}/build/x64/*/lib/OpenCVConfig.cmake")
    if(_configs)
      list(GET _configs 0 _config)
      get_filename_component(_cfg_dir "${_config}" DIRECTORY)
      set(OpenCV_DIR "${_cfg_dir}" PARENT_SCOPE)
      set(C_ACTUAL_OPENCV_ROOT "${_root}" PARENT_SCOPE)
      set(C_ACTUAL_OPENCV_MODE "manual" PARENT_SCOPE)
      return()
    endif()
  endforeach()

  # Fall back to an installed OpenCV.
  find_package(OpenCV QUIET COMPONENTS core imgproc imgcodecs videoio)
  if(OpenCV_FOUND)
    message(STATUS "c_actual: using installed OpenCV ${OpenCV_VERSION} (${OpenCV_DIR})")
    set(C_ACTUAL_OPENCV_MODE "package" PARENT_SCOPE)
    # find_package() ran inside this function, so its variables are local.
    # Propagate the actual package results instead of leaving the parent with
    # empty OpenCV_INCLUDE_DIRS/OpenCV_LIBS (which caused C1083).
    set(OpenCV_INCLUDE_DIRS "${OpenCV_INCLUDE_DIRS}" PARENT_SCOPE)
    set(OpenCV_LIBS "${OpenCV_LIBS}" PARENT_SCOPE)
    set(OpenCV_BIN_DIR "${OpenCV_BIN_DIR}" PARENT_SCOPE)
    set(OpenCV_VERSION "${OpenCV_VERSION}" PARENT_SCOPE)
    return()
  endif()

  message(FATAL_ERROR
    "OpenCV not found. Pass -DC_ACTUAL_OPENCV_ROOT=<dir> (containing build/) "
    "or install OpenCV with a CMake package.")
endfunction()

c_actual_find_onnxruntime()
if(TARGET pipeline_module_api)
  set(C_ACTUAL_OPENCV_MODE "package")
else()
  c_actual_find_opencv()
endif()

# Resolve OpenCV now (the finder only pointed OpenCV_DIR at the package config).
if(C_ACTUAL_OPENCV_MODE STREQUAL "manual")
  find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs videoio)
  message(STATUS "c_actual: OpenCV ${OpenCV_VERSION} via ${OpenCV_DIR}")
  message(STATUS "c_actual: OpenCV libs = ${OpenCV_LIBS} | bin = ${OpenCV_BIN_DIR}")
endif()
message(STATUS "c_actual: ONNX Runtime root = ${C_ACTUAL_ONNXRUNTIME_ROOT}")

# ---------------------------------------------------------------- library
add_library(c_actual STATIC
  src/perception_engine.cpp
  src/yolo_detector_onnx.cpp
  src/balltrack_onnx.cpp
  src/preprocessing.cpp
  src/postprocessing.cpp
)

target_include_directories(c_actual
  PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
    ${OpenCV_INCLUDE_DIRS}
  PRIVATE
    "${C_ACTUAL_ONNXRUNTIME_ROOT}/include"
)

if(C_ACTUAL_OPENCV_MODE STREQUAL "manual")
  # OpenCV_LIBS and OpenCV_INCLUDE_DIRS come from the package config (imported
  # targets carry their own include dirs, so consumers of our header see them too).
  target_link_libraries(c_actual PUBLIC ${OpenCV_LIBS})
  set(_c_actual_opencv_bin "${OpenCV_BIN_DIR}")
else()
  target_link_libraries(c_actual PUBLIC ${OpenCV_LIBS})
  set(_c_actual_opencv_bin "${OpenCV_BIN_DIR}")
endif()

# Link the import library by ABSOLUTE path: the repo path may contain non-ASCII
# characters, in which case a bare "/LIBPATH:..." + name does not resolve.
if(NOT EXISTS "${C_ACTUAL_ONNXRUNTIME_ROOT}/lib/onnxruntime.lib")
  message(FATAL_ERROR "onnxruntime.lib not found under ${C_ACTUAL_ONNXRUNTIME_ROOT}/lib")
endif()
target_link_libraries(c_actual PRIVATE "${C_ACTUAL_ONNXRUNTIME_ROOT}/lib/onnxruntime.lib")
target_include_directories(c_actual PRIVATE "${C_ACTUAL_ONNXRUNTIME_ROOT}/include")

# Ship the runtime DLLs next to the executables so the demo runs out of the box.
set(C_ACTUAL_RUNTIME_DLLS "${C_ACTUAL_ONNXRUNTIME_ROOT}/lib/onnxruntime.dll")
if(DEFINED _c_actual_opencv_bin AND EXISTS "${_c_actual_opencv_bin}")
  file(GLOB _opencv_dlls "${_c_actual_opencv_bin}/opencv_*.dll")
  list(APPEND C_ACTUAL_RUNTIME_DLLS ${_opencv_dlls})
endif()

# ------------------------------------------------- DetectorBackend bridge
if(C_ACTUAL_BUILD_PIPELINE_BRIDGE OR TARGET pipeline_module_api)
  if(TARGET pipeline_module_api)
    set(C_ACTUAL_PIPELINE_INCLUDE "${CMAKE_CURRENT_SOURCE_DIR}/../../include")
  endif()
  if(NOT C_ACTUAL_PIPELINE_INCLUDE)
    message(FATAL_ERROR
      "C_ACTUAL_BUILD_PIPELINE_BRIDGE=ON requires -DC_ACTUAL_PIPELINE_INCLUDE=<software/pc_pipeline/include>")
  endif()
  add_library(c_actual_pipeline_bridge STATIC src/detector_backend_c_actual.cpp)
  target_link_libraries(c_actual_pipeline_bridge PUBLIC c_actual)
  target_include_directories(c_actual_pipeline_bridge
    PUBLIC "${C_ACTUAL_PIPELINE_INCLUDE}"
    PRIVATE "${C_ACTUAL_ONNXRUNTIME_ROOT}/include")
  if(C_ACTUAL_JSON_INCLUDE)
    target_include_directories(c_actual_pipeline_bridge PRIVATE "${C_ACTUAL_JSON_INCLUDE}")
  endif()
  if(MSVC)
    target_compile_options(c_actual_pipeline_bridge PRIVATE /utf-8)
  endif()
  if(TARGET pipeline_module_api)
    target_link_libraries(c_actual_pipeline_bridge PUBLIC pipeline_module_api)
    add_library(pipeline_c_module ALIAS c_actual_pipeline_bridge)
  endif()
endif()
if(MSVC)
  target_compile_options(c_actual PUBLIC /utf-8)
endif()
