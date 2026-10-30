# A completed measurement remains in JSON files; keep the serial console concise.
field_run() {
 if "$@" >> "$field_session_log" 2>&1; then
  return 0
 else
  field_step_rc=$?
  printf 'FIELD_STEP_FAILED status=%s log=%s\n' "$field_step_rc" "$field_session_log" >&2
  tail -n 10 "$field_session_log" >&2
  return "$field_step_rc"
 fi
}

field_measurement_saved() {
 python3 -c 'import json,sys; p=sys.argv[1]; j=json.load(open(p+"/measurement-complete.json")); print("MEASUREMENT_SAVED status="+j["status"]+" motion="+j["motion_status"],flush=True)' "$case_path"
}
