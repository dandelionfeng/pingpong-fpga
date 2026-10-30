#!/bin/sh
set -e
BUILD_DIR=${BUILD_DIR:-build}
cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release "$@"
cmake --build "$BUILD_DIR" -j"$(nproc)"
echo "built: $BUILD_DIR/rknn_v3_detect_filtered"
echo "run  : ./$BUILD_DIR/rknn_v3_detect_filtered --model ../v3_960_fp16_dfl_layout.rknn --input frame.raw --width 1920 --height 1080"
