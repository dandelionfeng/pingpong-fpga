#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
name=${1:?NAME};manifest=${2:?INPUT_MANIFEST}
. "$task_root/field_parameters.sh"
field_performance
python3 -B "$task_root/field_workflow.py" recorded --name "$name" --input "$manifest"
