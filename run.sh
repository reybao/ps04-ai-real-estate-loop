#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  bash run.sh
  bash run.sh --approve runs/RUN_ID
  bash run.sh --propose-revision runs/RUN_ID
  bash run.sh --package runs/RUN_ID

The normal mode creates a new live run, collects and processes evidence, creates
the three-piece series, checks it, and stops for human review. Package mode
rechecks an existing run and prepares only already-approved artifacts.
Approve mode asks for a human decision and packages only after approval.
Proposal mode reuses a recorded API revision request without applying it.
EOF
}

require_component() {
  local relative="$1"
  if [[ ! -s "$ROOT/$relative" ]]; then
    printf 'error: required component is not implemented: %s\n' "$relative" >&2
    return 1
  fi
}

write_run_json() {
  local run_dir="$1"
  local run_id="$2"
  local started_at="$3"
  local as_of_date="$4"
  local previous_run_id="$5"
  python3 - "$run_dir/run.json" "$run_id" "$started_at" "$as_of_date" "$previous_run_id" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = {
    "run_id": sys.argv[2],
    "started_at": sys.argv[3],
    "as_of_date": sys.argv[4],
    "mode": "live",
    "previous_run_id": sys.argv[5] or None,
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

refresh_summary() {
  local run_dir="$1"
  local temporary result
  temporary="$(mktemp "$run_dir/.summary.XXXXXX")" || return 1
  bash "$ROOT/reporting/summarize_run.sh" "$run_dir" >"$temporary"
  result=$?
  if [[ "$result" -eq 0 ]]; then
    mv "$temporary" "$run_dir/summary.json"
    cat "$run_dir/summary.json"
    return 0
  fi
  rm -f "$temporary"
  return "$result"
}

run_live() {
  ps04_require_command python3
  ps04_validate_live_configuration || return $?

  local started_at as_of_date run_id previous_run_id run_dir
  started_at="$(ps04_now_utc)"
  as_of_date="${started_at%%T*}"
  run_id="$(ps04_new_run_id)" || return 1
  previous_run_id="$(ps04_previous_live_run_id)" || return 1
  run_dir="$ROOT/runs/$run_id"

  mkdir -p "$run_dir"/{config,prompts,logs,candidates,articles,video_scripts}
  cp "$ROOT/config/project.json" "$ROOT/config/sources.json" \
    "$ROOT/config/editorial_policy.md" "$run_dir/config/"
  cp "$ROOT/prompts/"*.md "$run_dir/prompts/"
  write_run_json "$run_dir" "$run_id" "$started_at" "$as_of_date" "$previous_run_id"

  local status=0 error_message=""
  local component
  for component in data/store.sh workflows/collect_sources.sh workflows/create_series.sh reporting/summarize_run.sh; do
    if ! require_component "$component"; then
      status=1
      error_message="pipeline implementation is incomplete; missing $component"
      break
    fi
  done

  if [[ "$status" -eq 0 ]] && ! bash "$ROOT/data/store.sh" init; then
    status=1
    error_message="evidence store initialization failed"
  fi

  local collect_status=0
  if [[ "$status" -eq 0 ]]; then
    bash "$ROOT/workflows/collect_sources.sh" "$run_dir"
    collect_status=$?
    if [[ "$collect_status" -ne 0 && ! -s "$run_dir/eligible.jsonl" ]]; then
      status=1
      error_message="collection workflow failed without usable eligible evidence"
    fi
  fi

  if [[ "$status" -eq 0 ]]; then
    if ! bash "$ROOT/workflows/create_series.sh" "$run_dir"; then
      status=1
      error_message="series workflow failed"
    elif [[ "$collect_status" -ne 0 ]]; then
      error_message="series completed with explicitly incomplete source coverage"
    fi
  fi

  local finished_at
  finished_at="$(ps04_now_utc)"
  if [[ "$status" -eq 0 ]]; then
    ps04_write_receipt "$run_dir" "run" "completed" "null" "null" \
      "$started_at" "$finished_at" "bash" "0" "$error_message"
  else
    ps04_write_receipt "$run_dir" "run" "failed" "null" "null" \
      "$started_at" "$finished_at" "bash" "0" "$error_message"
  fi

  if ! refresh_summary "$run_dir"; then
    printf 'error: unable to create summary for %s\n' "$run_dir" >&2
    return 1
  fi
  return "$status"
}

run_package() {
  ps04_require_command python3
  local requested="$1"
  local run_dir
  run_dir="$(ps04_assert_run_dir "$requested")" || return $?
  [[ -f "$run_dir/run.json" ]] || ps04_die 2 "run.json not found in $run_dir"

  local started_at status=0 error_message=""
  started_at="$(ps04_now_utc)"
  if ! require_component review/check_content.sh || ! require_component publishing/prepare_package.sh || ! require_component reporting/summarize_run.sh; then
    status=1
    error_message="package implementation is incomplete"
  fi

  local temporary
  if [[ "$status" -eq 0 ]]; then
    temporary="$(mktemp "$run_dir/.review.XXXXXX")" || return 1
    if bash "$ROOT/review/check_content.sh" "$run_dir" >"$temporary"; then
      mv "$temporary" "$run_dir/review.json"
    else
      status=1
      error_message="content assessment could not run"
      rm -f "$temporary"
    fi
  fi

  if [[ "$status" -eq 0 ]]; then
    temporary="$(mktemp "$run_dir/.package-manifest.XXXXXX")" || return 1
    if bash "$ROOT/publishing/prepare_package.sh" "$run_dir" >"$temporary"; then
      mkdir -p "$run_dir/package"
      mv "$temporary" "$run_dir/package/manifest.json"
    else
      status=1
      error_message="package preparation failed; verify current review and human approval"
      rm -f "$temporary"
    fi
  fi

  local finished_at
  finished_at="$(ps04_now_utc)"
  if [[ "$status" -eq 0 ]]; then
    ps04_write_receipt "$run_dir" "run-package" "completed" "null" "null" \
      "$started_at" "$finished_at" "bash" "0" ""
  else
    ps04_write_receipt "$run_dir" "run-package" "failed" "null" "null" \
      "$started_at" "$finished_at" "bash" "0" "$error_message"
  fi
  refresh_summary "$run_dir" || return 1
  return "$status"
}

run_approve() {
  ps04_require_command python3
  local requested="$1" run_dir decision_status temporary
  run_dir="$(ps04_assert_run_dir "$requested")" || return $?
  [[ -f "$run_dir/run.json" ]] || ps04_die 2 "run.json not found in $run_dir"
  if ! require_component review/check_content.sh || ! require_component review/approve_run.py; then
    return 1
  fi
  temporary="$(mktemp "$run_dir/.review.XXXXXX")" || return 1
  if bash "$ROOT/review/check_content.sh" "$run_dir" >"$temporary"; then
    mv "$temporary" "$run_dir/review.json"
  else
    rm -f "$temporary"
    printf 'error: content assessment could not run\n' >&2
    return 1
  fi
  refresh_summary "$run_dir" >/dev/null || return 1
  python3 "$ROOT/review/approve_run.py" "$run_dir"
  decision_status=$?
  case "$decision_status" in
    0) run_package "$run_dir" ;;
    3)
      refresh_summary "$run_dir" >/dev/null || return 1
      printf 'Run status: awaiting_review; existing package files must not be used until a new approval and package are prepared.\n'
      run_propose_revision "$run_dir"
      return $?
      ;;
    4) return 0 ;;
    *) return "$decision_status" ;;
  esac
}

run_propose_revision() {
  ps04_require_command python3
  local requested="$1" run_dir
  run_dir="$(ps04_assert_run_dir "$requested")" || return $?
  [[ -f "$run_dir/run.json" ]] || ps04_die 2 "run.json not found in $run_dir"
  require_component review/propose_revision.py || return 1
  python3 "$ROOT/review/propose_revision.py" "$run_dir"
}

case "$#" in
  0)
    run_live
    exit $?
    ;;
  1)
    if [[ "$1" == "--help" || "$1" == "-h" ]]; then
      usage
      exit 0
    fi
    usage >&2
    exit 2
    ;;
  2)
    if [[ "$1" == "--approve" ]]; then
      run_approve "$2"
      exit $?
    fi
    if [[ "$1" == "--propose-revision" ]]; then
      run_propose_revision "$2"
      exit $?
    fi
    if [[ "$1" == "--package" ]]; then
      run_package "$2"
      exit $?
    fi
    usage >&2
    exit 2
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
