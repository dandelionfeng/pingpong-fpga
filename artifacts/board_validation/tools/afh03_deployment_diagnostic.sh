#!/bin/sh
# AFH03 / RK3576J deployment diagnostic.  Run this ON THE BOARD:
#   sh afh03_deployment_diagnostic.sh --binary /userdata/build/motion7_chain \
#      --model /userdata/v3_960_fp16_dfl_layout.rknn \
#      --out /userdata/AFH03_DEPLOYMENT_DIAGNOSTIC.txt
# It only reads system state; it does not load or benchmark the model.
set -u

OUT="AFH03_DEPLOYMENT_DIAGNOSTIC.txt"
BINARY=""
MODEL=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --out) OUT=$2; shift 2 ;;
    --binary) BINARY=$2; shift 2 ;;
    --model) MODEL=$2; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

: > "$OUT"
say() { printf '%s\n' "$*" | tee -a "$OUT"; }
section() { say ""; say "===== $* ====="; }
have() { command -v "$1" >/dev/null 2>&1; }
run() {
  label=$1; shift
  printf '%-42s' "$label ..." | tee -a "$OUT"
  if "$@" >>"$OUT" 2>&1; then
    say " PASS"
  else
    say " FAIL/UNKNOWN"
  fi
}
value() {
  label=$1; shift
  printf '%-42s' "$label" | tee -a "$OUT"
  "$@" 2>&1 | tee -a "$OUT" || say " (command failed)"
}

say "AFH03_DEPLOYMENT_DIAGNOSTIC"
say "generated_at=$(date -Iseconds 2>/dev/null || date)"
say "host=$(hostname 2>/dev/null || cat /proc/sys/kernel/hostname 2>/dev/null || echo unknown)"
say "script=$0"
say "binary=${BINARY:-<not supplied>}"
say "model=${MODEL:-<not supplied>}"

section "1. chip / kernel / OS"
value "uname" uname -a
value "os-release" sh -c 'cat /etc/os-release 2>/dev/null || true'
if [ -r /proc/device-tree/compatible ]; then
  compatible=$(tr -d '\000' </proc/device-tree/compatible 2>/dev/null)
  say "device-tree compatible=$compatible"
  case "$compatible" in
    *rk3576*) say "RK3576_COMPATIBLE=PASS" ;;
    *) say "RK3576_COMPATIBLE=FAIL" ;;
  esac
else
  say "RK3576_COMPATIBLE=NOT_TESTED (no /proc/device-tree/compatible)"
fi
if [ -r /proc/cpuinfo ]; then
  value "cpuinfo model" sh -c "grep -m1 -E 'model name|Hardware|Processor' /proc/cpuinfo || true"
  say "cpu_count=$(grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo unknown)"
fi
value "meminfo" sh -c "grep -E '^(MemTotal|MemAvailable):' /proc/meminfo 2>/dev/null || true"

section "2. RKNPU driver / device"
if [ -d /dev ]; then
  value "rknpu devices" sh -c 'ls -l /dev/rknpu* 2>/dev/null || true'
fi
for f in /sys/kernel/debug/rknpu/version /sys/kernel/debug/rknpu/load /sys/kernel/debug/rknpu/freq; do
  if [ -r "$f" ]; then
    value "$f" cat "$f"
  else
    say "$f = NOT_TESTED (missing or permission denied)"
  fi
done
value "rknpu kernel messages" sh -c "dmesg 2>/dev/null | grep -i -E 'rknpu|rknn' | tail -20 || true"
value "npu devfreq" sh -c 'for d in /sys/class/devfreq/*; do [ -d "$d" ] || continue; n=$(cat "$d/name" 2>/dev/null || true); case "$n" in *npu*|*rknpu*) echo "$n cur=$(cat "$d/cur_freq" 2>/dev/null) avail=$(cat "$d/available_frequencies" 2>/dev/null)";; esac; done'
value "npu thermal" sh -c 'for z in /sys/class/thermal/thermal_zone*; do [ -r "$z/type" ] || continue; t=$(cat "$z/type"); case "$t" in *npu*|*soc*|*gpu*) echo "$t $(cat "$z/temp" 2>/dev/null)";; esac; done'

section "3. RKNN runtime / toolkit"
if have ldconfig; then
  value "ldconfig rknn" sh -c 'ldconfig -p 2>/dev/null | grep -i rknn || true'
fi
value "librknnrt locations" sh -c 'find /usr /lib /opt /userdata -name "librknnrt.so*" 2>/dev/null | head -20'
if have strings; then
  lib=$(find /usr /lib /opt /userdata -name 'librknnrt.so*' 2>/dev/null | head -1)
  if [ -n "$lib" ]; then
    value "librknnrt version strings" sh -c "strings '$lib' | grep -i -m5 -E 'version|librknnrt' || true"
  else
    say "librknnrt version strings = NOT_TESTED (library not found)"
  fi
fi
if have python3; then
  value "rknn-toolkit2/lite2" sh -c "python3 - <<'PY'
try:
    import rknn
    print('rknn package:', getattr(rknn, '__version__', 'unknown'), getattr(rknn, '__file__', ''))
except Exception as exc:
    print('rknn package: NOT_AVAILABLE', repr(exc))
PY"
else
  say "python3 = NOT_TESTED"
fi

section "4. RGA / camera / GRAY8"
value "rga devices" sh -c 'ls -l /dev/rga* 2>/dev/null || true'
if have v4l2-ctl; then
  value "v4l2 devices" v4l2-ctl --list-devices
  for dev in /dev/video*; do
    [ -e "$dev" ] || continue
    section "v4l2 $dev formats"
    v4l2-ctl --device "$dev" --list-formats-ext 2>&1 | tee -a "$OUT" || true
    if v4l2-ctl --device "$dev" --list-formats-ext 2>/dev/null | grep -Eiq 'GREY|GRAY|Y8|Y10|Y12'; then
      say "$dev GRAY8_OR_GREY=PASS"
    else
      say "$dev GRAY8_OR_GREY=NOT_FOUND"
    fi
  done
else
  say "v4l2-ctl = NOT_TESTED (install v4l-utils)"
fi
value "ov9281 i2c/driver" sh -c "dmesg 2>/dev/null | grep -i -E 'ov9281|ov928' | tail -20 || true"

section "5. binary and dynamic libraries"
if [ -n "$BINARY" ]; then
  if [ -x "$BINARY" ]; then
    say "binary exists and is executable: $BINARY"
    value "file" file "$BINARY"
    if have ldd; then
      value "ldd" ldd "$BINARY"
      missing=$(ldd "$BINARY" 2>/dev/null | grep -c 'not found' || true)
      say "ldd_missing_count=$missing"
    else
      say "ldd = NOT_TESTED"
    fi
  else
    say "BINARY=FAIL (missing or not executable: $BINARY)"
  fi
else
  say "BINARY=NOT_TESTED (pass --binary)"
fi

section "6. model file"
if [ -n "$MODEL" ]; then
  if [ -r "$MODEL" ]; then
    value "model file" file "$MODEL"
    if have sha256sum; then
      value "model sha256" sha256sum "$MODEL"
    fi
    say "model_size=$(wc -c <"$MODEL")"
  else
    say "MODEL=FAIL (not readable: $MODEL)"
  fi
else
  say "MODEL=NOT_TESTED (pass --model)"
fi

section "7. summary"
if [ "${compatible:-}" ] && printf '%s' "$compatible" | grep -q 'rk3576'; then
  say "BOARD_STATUS=AFH03_CHIP_MATCH"
else
  say "BOARD_STATUS=BLOCKED_NOT_AFH03 (run on the RK3576J board for a valid result)"
fi
say "This report is evidence only for the machine it ran on."
say "Do not copy PC/simulator FPS into this file."
say "AFH03_DEPLOYMENT_DIAGNOSTIC_DONE"
