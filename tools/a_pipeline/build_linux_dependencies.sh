#!/usr/bin/env bash
set -euo pipefail
taskRepo="${1:-/mnt/c/FPGA competition}"
taskRoot="$HOME/.local/share/afh03-a-pipeline"
mkdir -p "$taskRoot"
if [[ ! -f "$taskRoot/opencv/lib/cmake/opencv4/OpenCVConfig.cmake" ]]; then
  if [[ ! -d "$taskRoot/opencv-source" ]]; then cp -r "$taskRepo/.tools/opencv413/opencv/sources" "$taskRoot/opencv-source"; fi
  cmake -S "$taskRoot/opencv-source" -B "$taskRoot/opencv-build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$taskRoot/opencv" -DBUILD_LIST=core,imgproc,imgcodecs,videoio,highgui,calib3d,video,dnn -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_python3=OFF -DWITH_IPP=OFF -DWITH_OPENCL=OFF -DWITH_FFMPEG=OFF -DWITH_GTK=OFF -DWITH_QT=OFF -DBUILD_JAVA=OFF -DOPENCV_GENERATE_PKGCONFIG=ON
  cmake --build "$taskRoot/opencv-build" --parallel 4
  cmake --install "$taskRoot/opencv-build"
fi
printf 'OPENCV_DIR=%s\n' "$taskRoot/opencv/lib/cmake/opencv4"
