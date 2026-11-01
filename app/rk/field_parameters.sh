# Validated30.92 profile; capture first, then full-pair inference.
if [ -z "${task_root:-}" ]; then
  echo 'field_parameters.sh: task_root is not set; source it from a run_*.sh script' >&2
  return 1 2>/dev/null || exit 1
fi
repo_root=$(CDPATH= cd -- "$task_root/../.." && pwd)

has_opencv_core() {
  [ -d "$1" ] || return 1
  for _opencv_lib in "$1"/libopencv_core.so* "$1"/opencv_world*.dll; do
    [ -e "$_opencv_lib" ] && return 0
  done
  return 1
}

opencv_dir=
if [ -n "${CHAIN_OPENCV_LIB_DIR:-}" ]; then
  case "$CHAIN_OPENCV_LIB_DIR" in
    /*) opencv_dir=$CHAIN_OPENCV_LIB_DIR ;;
    *) opencv_dir=$repo_root/$CHAIN_OPENCV_LIB_DIR ;;
  esac
  if ! has_opencv_core "$opencv_dir"; then
    echo "field_parameters.sh: CHAIN_OPENCV_LIB_DIR does not contain an OpenCV core library: $opencv_dir" >&2
    return 1 2>/dev/null || exit 1
  fi
else
  for candidate in "$repo_root/opencv/lib" "$repo_root/third_party/opencv/lib" \
    "$repo_root/runtime/opencv/lib" "$task_root/opencv/lib" \
    /usr/local/lib /usr/lib/aarch64-linux-gnu /usr/lib64 /usr/lib /opt/opencv/lib; do
    if has_opencv_core "$candidate"; then
      opencv_dir=$candidate
      break
    fi
  done
fi
if [ -z "$opencv_dir" ]; then
  echo 'field_parameters.sh: OpenCV library directory not configured; set CHAIN_OPENCV_LIB_DIR to a directory containing libopencv_core.so* (or opencv_world*.dll), or install OpenCV in a standard prefix.' >&2
  return 1 2>/dev/null || exit 1
fi
export CHAIN_OPENCV_LIB_DIR="$opencv_dir"
export LD_LIBRARY_PATH="$opencv_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$task_root/pydeps${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export CHAIN_FPGA_FEATURE_MODE=0 CHAIN_INLINE_PREPROCESS=none
export CHAIN_HAND_STRIDE=1 CHAIN_HAND_STOP_ON_MASK=0
export CHAIN_STREAMING=1 CHAIN_PIN=1 CHAIN_CV_THREADS=1 CHAIN_FAST_BINARY_MORPH=1
export CHAIN_TESO=1 CHAIN_TESO_STRIDE=30 CHAIN_PACE_FPS=0 FIELD_CHAIN_MODE=batch
export C_OPT_RAW_INPUT=1 C_OPT_QOUTPUT=1 C_OPT_ZINPUT=1 C_OPT_CORE=split
export CHAIN_PARALLEL_EYES=1 C_OPT_DUP_CONTEXT=1 CHAIN_HAND_KINEMATIC_MODE=stop
export CHAIN_KINEMATIC_HELPER="$task_root/online_kinematics.py"
export FIELD_RESULT_ROOT=/root/pingpong-quick-field-3092-results
unset CHAIN_BALL_MODEL CHAIN_VERIFY_FPGA_MASK PIPELINE_TESO_SYNC_EVAL
unset CHAIN_CAMERA CHAIN_AUTOSTOP_FIT CHAIN_CAPTURE_MAX_SECONDS
unset C_RKNN_VERIFY_NATIVE C_RKNN_VERIFY_PREPROCESS
export PIPELINE_B_DIAGNOSTIC_RELAX=1 PIPELINE_MASK_RELEASE=1

field_quiet_console() { dmesg -n 4; }
field_quiet_console
field_restore() {
 if [ -n "${task_governors:-}" ] && [ -f "$task_governors" ]; then
  while read -r task_path task_value; do printf '%s' "$task_value" > "$task_path"; done < "$task_governors"
  rm -f "$task_governors"
 fi
 # Keep camera/driver INFO and WARNING messages off the interactive console.
 # All priorities remain available in the kernel ring buffer through dmesg.
 dmesg -n 4
}
field_performance() {
 task_governors=$(mktemp /tmp/quick-field-governors.XXXXXX)
 trap 'field_restore' EXIT
 for task_path in /sys/devices/system/cpu/cpufreq/policy*/scaling_governor \
  /sys/class/devfreq/27700000.npu/governor /sys/class/devfreq/dmc/governor; do
  printf '%s %s\n' "$task_path" "$(cat "$task_path")" >> "$task_governors"
  printf performance > "$task_path"
 done
}
