#!/usr/bin/env bash

# Shared invocation and receipt handling for collectors that read RSS or Atom.

ps04_run_syndication_collector() {
  local run_dir="$1"
  local kind="$2"
  local stage="$3"
  local sources_path="$run_dir/config/sources.json"
  [[ -f "$sources_path" ]] || ps04_die 2 "missing run source snapshot: $sources_path"

  local started_at finished_at output_temp error_temp status source_count output_count receipt_status error_message
  started_at="$(ps04_now_utc)"
  output_temp="$(mktemp "$run_dir/.collector-output.XXXXXX")" || return 1
  error_temp="$(mktemp "$run_dir/.collector-error.XXXXXX")" || return 1

  python3 "$PS04_ROOT/collectors/collect_syndication.py" \
    --kind "$kind" --sources "$sources_path" >"$output_temp" 2>"$error_temp"
  status=$?
  finished_at="$(ps04_now_utc)"
  source_count="$(python3 - "$sources_path" "$kind" <<'PY'
import json, sys
sources = json.load(open(sys.argv[1], encoding="utf-8"))
print(sum(1 for source in sources if isinstance(source, dict) and source.get("kind") == sys.argv[2]))
PY
)"
  output_count="$(awk 'NF {count += 1} END {print count + 0}' "$output_temp")"
  error_message="$(tr '\n' ' ' <"$error_temp" | cut -c1-1000)"

  if [[ "$status" -eq 0 ]]; then
    receipt_status="completed"
  elif [[ "$output_count" -gt 0 ]]; then
    receipt_status="incomplete"
  else
    receipt_status="failed"
  fi
  ps04_write_receipt "$run_dir" "$stage" "$receipt_status" "$source_count" "$output_count" \
    "$started_at" "$finished_at" "python3,urllib,xml.etree" "0" "$error_message"

  if [[ -s "$error_temp" ]]; then
    sed "s/^/$stage: /" "$error_temp" >&2
  fi
  cat "$output_temp"
  rm -f "$output_temp" "$error_temp"
  return "$status"
}
