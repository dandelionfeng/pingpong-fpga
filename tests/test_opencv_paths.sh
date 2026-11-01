#!/bin/sh
# Cross-machine path-resolution regression test for app/rk/field_parameters.sh.
# Uses fake empty OpenCV core files; it does not need a real OpenCV install.
set -u
dmesg() { :; }
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=${TMPDIR:-/tmp}/pingpong_opencv_path_test
rm -rf "$tmp"
mkdir -p "$tmp/a/opencv/lib" "$tmp/rootB/app/rk" "$tmp/rootB/opencv/lib" \
         "$tmp/rootC/app/rk" "$tmp/rootC/opencv/lib" "$tmp/rootD/app/rk" \
         "$tmp/rootD/opencv/lib" "$tmp/empty/app/rk"
for root in "$tmp/rootB" "$tmp/rootC" "$tmp/rootD" "$tmp/empty"; do
  cp "$repo_root/app/rk/field_parameters.sh" "$root/app/rk/field_parameters.sh"
done
: > "$tmp/a/opencv/lib/libopencv_core.so.4"
: > "$tmp/rootB/opencv/lib/libopencv_core.so.4"
: > "$tmp/rootC/opencv/lib/libopencv_core.so.4"
: > "$tmp/rootD/opencv/lib/libopencv_core.so.4"

run_case() {
  name=$1
  root=$2
  envdir=$3
  cwd=$4
  unset CHAIN_OPENCV_LIB_DIR 2>/dev/null || true
  if [ -n "$envdir" ]; then
    export CHAIN_OPENCV_LIB_DIR="$envdir"
  fi
  export LD_LIBRARY_PATH=/opt/original
  ( cd "$cwd" && task_root="$root/app/rk" && . "$root/app/rk/field_parameters.sh" && printf '%s|%s|%s\n' "$name" "$CHAIN_OPENCV_LIB_DIR" "$LD_LIBRARY_PATH" )
}

printf 'A '; run_case A "$tmp/rootB" "$tmp/a/opencv/lib" /tmp
printf 'B '; run_case B "$tmp/rootB" "" /tmp
printf 'C '; run_case C "$tmp/rootC" "" /tmp
printf 'D '; run_case D "$tmp/rootD" "" "$repo_root"
printf 'E '
unset CHAIN_OPENCV_LIB_DIR 2>/dev/null || true
export LD_LIBRARY_PATH=/opt/original
if ( task_root="$tmp/empty/app/rk" && . "$tmp/empty/app/rk/field_parameters.sh" ) 2>"$tmp/e.err"; then
  echo UNEXPECTED_PASS
else
  echo "EXPECTED_FAIL"
  cat "$tmp/e.err"
fi
