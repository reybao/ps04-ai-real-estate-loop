#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

[[ "$#" -eq 1 ]] || ps04_die 2 "usage: bash workflows/create_series.sh RUN_DIR"
RUN_DIR="$1"
[[ -f "$RUN_DIR/eligible.jsonl" ]] || ps04_die 2 "RUN_DIR must contain eligible.jsonl: $RUN_DIR"
mkdir -p "$RUN_DIR/logs" "$RUN_DIR/model" "$RUN_DIR/articles" "$RUN_DIR/video_scripts"

STARTED_AT="$(ps04_now_utc)"
INPUT_COUNT="$(awk 'NF {n += 1} END {print n + 0}' "$RUN_DIR/eligible.jsonl")"
STATUS=0
ERROR_MESSAGE=""

run_to_artifact() {
  local artifact="$1"
  shift
  local temporary code
  temporary="$(mktemp "$RUN_DIR/.series-stage.XXXXXX")" || return 1
  "$@" >"$temporary"
  code=$?
  if [[ "$code" -eq 0 ]]; then
    mv "$temporary" "$RUN_DIR/$artifact"
    return 0
  fi
  rm -f "$temporary"
  return "$code"
}

if [[ "$INPUT_COUNT" -eq 0 ]]; then
  STATUS=1
  ERROR_MESSAGE="no eligible evidence is available"
elif ! run_to_artifact "decisions.jsonl" bash "$ROOT/editorial/select_items.sh" "$RUN_DIR" <"$RUN_DIR/eligible.jsonl"; then
  STATUS=1
  ERROR_MESSAGE="editorial selection failed"
elif ! run_to_artifact "briefs.jsonl" bash "$ROOT/editorial/create_briefs.sh" "$RUN_DIR" <"$RUN_DIR/decisions.jsonl"; then
  STATUS=1
  ERROR_MESSAGE="brief creation or evidence validation failed"
elif ! run_to_artifact "articles.jsonl" bash "$ROOT/content/write_articles.sh" "$RUN_DIR" <"$RUN_DIR/briefs.jsonl"; then
  STATUS=1
  ERROR_MESSAGE="article generation failed"
elif ! run_to_artifact "video_scripts.jsonl" bash "$ROOT/content/write_video_scripts.sh" "$RUN_DIR" <"$RUN_DIR/briefs.jsonl"; then
  STATUS=1
  ERROR_MESSAGE="video-script generation failed"
elif ! run_to_artifact "review.json" bash "$ROOT/review/check_content.sh" "$RUN_DIR"; then
  STATUS=1
  ERROR_MESSAGE="content assessment could not run"
elif ! python3 - "$RUN_DIR/review.json" <<'PY'
import json,sys
raise SystemExit(0 if json.load(open(sys.argv[1], encoding='utf-8')).get('passed') is True else 1)
PY
then
  STATUS=1
  ERROR_MESSAGE="content assessment found blocking errors"
fi

FINISHED_AT="$(ps04_now_utc)"
if [[ "$STATUS" -eq 0 ]]; then
  ps04_write_receipt "$RUN_DIR" "create-series-workflow" "completed" "$INPUT_COUNT" "3" \
    "$STARTED_AT" "$FINISHED_AT" "bash,openai" "null" ""
else
  ps04_write_receipt "$RUN_DIR" "create-series-workflow" "failed" "$INPUT_COUNT" "null" \
    "$STARTED_AT" "$FINISHED_AT" "bash,openai" "null" "$ERROR_MESSAGE"
fi
exit "$STATUS"
