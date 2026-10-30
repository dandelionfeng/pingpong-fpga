#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -eq 0 ] || [ "$1" = --help ]; then
 echo 'Usage: sh run_capture.sh [NAME] /dev/videoN [auto|EXPOSURE] [seconds=30]'
 echo 'Original MJPEG capture first; then30.92 profile analysis; completed results stay on RK.'
 exit 0
fi
case "$1" in
 /dev/*) requested=auto;device=$1;exposure=${2:-auto};seconds=${3:-30};;
 *) requested=$1;device=${2:?Choose a supported USB camera};exposure=${3:-auto};seconds=${4:-30};;
esac
. "$task_root/field_parameters.sh"
field_performance
python3 -B "$task_root/field_workflow.py" camera --name "$requested" --device "$device" --exposure "$exposure" --seconds "$seconds"
