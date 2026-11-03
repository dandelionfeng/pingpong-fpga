#!/bin/sh
# Run ON THE AFH03 board, with the RKNN 2.5.0 runtime and FP16 model.
# It checks environment, model hash, model tensor attrs, memory, one inference,
# and writes AFH03_BOARD_VALIDATION.txt.  It does not modify the system.
set -u

OUT=AFH03_BOARD_VALIDATION.txt
BINARY=./rknn_v3_detect_dfl
MODEL=""
INPUT=""
WIDTH=1920
HEIGHT=1080
CORE_MASK=auto
EXPECT_SHA=1bcff6ff23f1a26428742e6a8e7c9acaf5b130171dbf2072cbaace6c62bcad0b

while [ "$#" -gt 0 ]; do
  case "$1" in
    --binary) BINARY=$2; shift 2 ;;
    --model) MODEL=$2; shift 2 ;;
    --input) INPUT=$2; shift 2 ;;
    --width) WIDTH=$2; shift 2 ;;
    --height) HEIGHT=$2; shift 2 ;;
    --core-mask) CORE_MASK=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 2 ;;
  esac
done

: > "$OUT"
say() { printf '%s\n' "$*" | tee -a "$OUT"; }
section() { say ""; say "===== $* ====="; }
have() { command -v "$1" >/dev/null 2>&1; }

say "AFH03_BOARD_VALIDATION"
say "generated_at=$(date -Iseconds 2>/dev/null || date)"
say "host=$(hostname 2>/dev/null || echo unknown)"
say "binary=$BINARY"
say "model=$MODEL"
say "input=$INPUT"
say "requested_core_mask=$CORE_MASK"

section "1. board and driver"
say "uname: $(uname -a 2>/dev/null || echo unknown)"
if [ -r /proc/device-tree/compatible ]; then
  compatible=$(tr -d '\000' </proc/device-tree/compatible)
  say "compatible=$compatible"
  case "$compatible" in *rk3576*) say "CHIP=PASS" ;; *) say "CHIP=FAIL" ;; esac
else
  say "CHIP=BLOCKED (no device-tree compatible)"
fi
for f in /sys/kernel/debug/rknpu/version /sys/kernel/debug/rknpu/load; do
  if [ -r "$f" ]; then say "$f=$(cat "$f")"; else say "$f=NOT_TESTED"; fi
done
say "rknpu_dmesg:"
dmesg 2>/dev/null | grep -i -E 'rknpu|rknn' | tail -10 | tee -a "$OUT" || true

section "2. runtime and model"
say "ldconfig_rknn:"
ldconfig -p 2>/dev/null | grep -i rknn | tee -a "$OUT" || true
RT=""
for c in "${LD_LIBRARY_PATH:-}/librknnrt.so" /usr/lib/librknnrt.so /lib/librknnrt.so ./librknnrt.so; do
  [ -r "$c" ] && RT=$c && break
done
if [ -n "$RT" ]; then
  say "runtime_path=$RT"
  say "runtime_version=$(strings "$RT" 2>/dev/null | grep -m1 -i 'librknnrt version' || echo unknown)"
  if strings "$RT" 2>/dev/null | grep -qiE 'librknnrt version: (2\.[5-9]|[3-9]\.)'; then
    say "RUNTIME_GE_2_5=PASS"
  else
    say "RUNTIME_GE_2_5=FAIL"
  fi
  say "runtime_sha256=$(sha256sum "$RT" | cut -d' ' -f1)"
else
  say "runtime_path=NOT_FOUND"
fi
if [ -n "$MODEL" ] && [ -r "$MODEL" ]; then
  actual=$(sha256sum "$MODEL" | cut -d' ' -f1)
  say "model_sha256=$actual"
  [ "$actual" = "$EXPECT_SHA" ] && say "MODEL_SHA=PASS" || say "MODEL_SHA=FAIL expected=$EXPECT_SHA"
  say "model_size=$(wc -c <"$MODEL")"
else
  say "MODEL=NOT_TESTED"
fi

section "3. binary dependencies"
if [ -x "$BINARY" ]; then
  file "$BINARY" 2>/dev/null | tee -a "$OUT" || true
  ldd "$BINARY" 2>&1 | tee -a "$OUT" || true
  say "binary_sha256=$(sha256sum "$BINARY" | cut -d' ' -f1)"
else
  say "BINARY=NOT_TESTED ($BINARY not executable)"
fi

section "4. init + tensor attributes + one inference"
if [ -x "$BINARY" ] && [ -r "$MODEL" ] && [ -r "$INPUT" ]; then
  TMP=$(mktemp)
  "$BINARY" --model "$MODEL" --input "$INPUT" --width "$WIDTH" --height "$HEIGHT" \
    --layout dfl --core-mask "$CORE_MASK" >"$TMP" 2>&1
  RCP=$?
  cat "$TMP" | tee -a "$OUT"
  say "inference_rc=$RCP"
  say "outputs_line=$(grep -m1 'outputs=' "$TMP" || true)"
  say "out64_lines=$(grep -c 'out\\[[0-9]*\\].*dims=\\[1,64,' "$TMP" || true)"
  say "out3_lines=$(grep -c 'out\\[[0-9]*\\].*dims=\\[1,3,' "$TMP" || true)"
  grep -q 'outputs=8' "$TMP" && say "OUTPUT_COUNT_8=PASS" || say "OUTPUT_COUNT_8=FAIL"
  grep -q 'dims=\\[1,64,18900\\]' "$TMP" && say "DFL_64x18900=PASS" || say "DFL_64x18900=FAIL"
  grep -q 'dims=\\[1,3,18900\\]' "$TMP" && say "CLASS_3x18900=PASS" || say "CLASS_3x18900=FAIL"
  grep -q 'memory weight_bytes=' "$TMP" && say "MEMORY_QUERY=PASS" || say "MEMORY_QUERY=NOT_TESTED"
  rm -f "$TMP"
else
  say "INFERENCE=NOT_TESTED (need --binary, --model, --input)"
fi

section "5. summary"
say "Do not write PC/simulator FPS here."
say "AFH03_BOARD_VALIDATION_DONE"
