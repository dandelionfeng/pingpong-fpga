#!/bin/sh
# PC-side cross-check WITHOUT the board: run the same decode/NMS logic on the ONNX export.
# This proves the C++ algorithms (letterbox, decode, NMS, coordinate restore) match Python,
# but it is NOT an RKNN test and must never be reported as board performance.
echo "Use tools/verify_decode_pc.py for the numerical cross-check."
echo "On the board: ./build.sh && ./build/rknn_v3_detect --model ../v3_960/v3_int8.rknn --input frame.raw --width 1920 --height 1080 --bench 500"
