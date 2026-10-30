#!/bin/sh
# Build on the board (or any aarch64 host with the RKNN runtime installed).
set -e
BUILD_DIR=${BUILD_DIR:-build}
cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release "$@"
cmake --build "$BUILD_DIR" -j"$(nproc)"
echo "built: $BUILD_DIR/rknn_v3_detect"
