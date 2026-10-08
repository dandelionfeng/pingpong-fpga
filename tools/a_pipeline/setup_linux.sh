#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y build-essential cmake ninja-build python3-venv python3-pip pkg-config libgl1-mesa-dev libegl1-mesa-dev libxkbcommon-dev libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 libglib2.0-0 libfreetype6 libx11-dev libxext-dev libsm-dev libice-dev libpng-dev libjpeg-dev zlib1g-dev libtiff-dev iverilog gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
