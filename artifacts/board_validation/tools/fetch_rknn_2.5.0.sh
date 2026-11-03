#!/bin/sh
# Fetch the official Rockchip RKNN 2.5.0 runtime + API header into ./rknn-2.5.0.
# This does not install into /usr/lib and does not modify the board firmware.
set -eu
DEST=${1:-./rknn-2.5.0}
mkdir -p "$DEST"
BASE=https://raw.githubusercontent.com/airockchip/rknn-toolkit2/v2.5.0/rknpu2/runtime/Linux/librknn_api
curl -L --retry 5 --max-time 300 -o "$DEST/rknn_api.h" "$BASE/include/rknn_api.h"
curl -L --retry 5 --max-time 300 -o "$DEST/librknnrt.so" "$BASE/aarch64/librknnrt.so"

echo "2d4160cd868efd7b83a72587e411c16d6972da5876e067bd73665cea778ce666  $DEST/rknn_api.h" | sha256sum -c -
echo "4b6cc575bedf8952b13db4b1190fa3b3d2ac213f00be774ff6ccd19d651970c0  $DEST/librknnrt.so" | sha256sum -c -
strings "$DEST/librknnrt.so" | grep -m1 'librknnrt version'
echo "RKNN_2.5.0_FETCH_OK"
