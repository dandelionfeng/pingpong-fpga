#!/bin/sh
# Explicit engineering diagnostic; production never falls back to CPU Mask.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$task_root/field_parameters.sh"
field_performance
python3 -B "$task_root/field_workflow.py" diagnostic --name "${1:?NAME}" --input "${2:?MANIFEST}"
