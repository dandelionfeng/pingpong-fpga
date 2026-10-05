#!/usr/bin/env bash
set -euo pipefail
taskSource=$(cd "$(dirname "$0")/../.." && pwd)
taskRoot="${A_PIPELINE_DEPS:-$HOME/.local/share/afh03-a-pipeline}"
taskBuild="${A_PIPELINE_BUILD:-$taskRoot/pipeline-build}"
cmake -S "$taskSource/software/pc_pipeline" -B "$taskBuild" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DPIPELINE_BUILD_GUI=ON \
  -DOpenCV_DIR="$taskRoot/opencv/lib/cmake/opencv4" \
  -DQt6_DIR="$taskRoot/qt/6.8.3/gcc_64/lib/cmake/Qt6" "$@"
cmake --build "$taskBuild" -j4
ctest --test-dir "$taskBuild" --output-on-failure
