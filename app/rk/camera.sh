#!/bin/sh
set -eu
dmesg -n 4
mode=${1:-list}
device=${2:-}
case "$mode" in
 list)
  v4l2-ctl --list-devices
  lsusb -t
  echo 'Use a USB UVC capture node, then run: sh camera.sh setup /dev/video73 auto 0'
  ;;
 setup)
  test -n "$device"
  exposure=${3:-auto};gain=${4:-0}
  v4l2-ctl -d "$device" --list-formats-ext
  controls=$(v4l2-ctl -d "$device" --list-ctrls-menus)
  printf '%s\n' "$controls"
  v4l2-ctl -d "$device" --set-fmt-video=width=2560,height=720,pixelformat=MJPG --set-parm=60
  control=
  if printf '%s' "$controls" | grep -qw exposure_auto; then control=exposure_auto; fi
  if printf '%s' "$controls" | grep -qw auto_exposure; then control=auto_exposure; fi
  test -n "$control" || { echo 'Camera exposure control is unavailable' >&2;exit 2; }
  case "$exposure" in
   auto|0)
    v4l2-ctl -d "$device" --set-ctrl="$control=3" || v4l2-ctl -d "$device" --set-ctrl="$control=0"
    ;;
   *[!0-9]*|'') echo 'Exposure must be auto or a positive integer' >&2;exit 2;;
   *)
    v4l2-ctl -d "$device" --set-ctrl="$control=1"
    if printf '%s' "$controls" | grep -qw exposure_absolute; then v4l2-ctl -d "$device" --set-ctrl="exposure_absolute=$exposure"; fi
    if printf '%s' "$controls" | grep -qw exposure_time_absolute; then v4l2-ctl -d "$device" --set-ctrl="exposure_time_absolute=$exposure"; fi
    ;;
  esac
  current=$(v4l2-ctl -d "$device" --get-ctrl="$control")
  printf '%s\n' "$current"
  case "$exposure" in auto|0)
   # v4l2-ctl menu controls can return "3 (Aperture Priority Mode)".
   # Compare only the leading integer, leaving the selected exposure unchanged.
   value=$(printf '%s\n' "$current" | sed -n "s/^[[:space:]]*$control:[[:space:]]*\([0-9][0-9]*\).*/\1/p")
   case "$value" in 0|3) ;; *) echo 'Camera did not retain automatic exposure' >&2;exit 2;; esac
  esac
  if printf '%s' "$controls" | grep -qw gain; then v4l2-ctl -d "$device" --set-ctrl="gain=$gain"; fi
  v4l2-ctl -d "$device" --get-fmt-video --get-parm --all
  ;;
 *) echo 'Usage: camera.sh list | camera.sh setup /dev/videoN [auto|EXPOSURE] [GAIN]' >&2;exit 2;;
esac
