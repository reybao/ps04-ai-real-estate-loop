#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

[[ "$#" -eq 1 ]] || ps04_die 2 "usage: bash editorial/select_items.sh RUN_DIR < eligible.jsonl"
RUN_DIR="$1"
[[ -f "$RUN_DIR/run.json" ]] || ps04_die 2 "RUN_DIR must contain run.json: $RUN_DIR"

STARTED_AT="$(ps04_now_utc)"
INPUT="$(mktemp "$RUN_DIR/.select-input.XXXXXX")" || exit 1
OUTPUT="$(mktemp "$RUN_DIR/.select-output.XXXXXX")" || exit 1
ERRORS="$(mktemp "$RUN_DIR/.select-errors.XXXXXX")" || exit 1
cat >"$INPUT"
INPUT_COUNT="$(awk 'NF {n += 1} END {print n + 0}' "$INPUT")"

python3 "$ROOT/editorial/select_items.py" "$RUN_DIR" "$INPUT" "$OUTPUT" 2>"$ERRORS"
STATUS=$?
if [[ -s "$ERRORS" ]]; then
  cp "$ERRORS" "$RUN_DIR/select_items_errors.txt"
  sed 's/^/select-items: /' "$ERRORS" >&2
else
  rm -f "$RUN_DIR/select_items_errors.txt"
fi
FINISHED_AT="$(ps04_now_utc)"
if [[ "$STATUS" -eq 0 ]]; then
  OUTPUT_COUNT="$(awk 'NF {n += 1} END {print n + 0}' "$OUTPUT")"
  MODEL="$(python3 - "$RUN_DIR/model/select-items.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1], encoding='utf-8')).get('model','openai'))
PY
)"
  ps04_write_receipt "$RUN_DIR" "select-items" "completed" "$INPUT_COUNT" "$OUTPUT_COUNT" \
    "$STARTED_AT" "$FINISHED_AT" "$MODEL" "null" ""
  cat "$OUTPUT"
else
  ERROR_MESSAGE="$(tr '\n' ' ' <"$ERRORS" | cut -c1-1000)"
  ps04_write_receipt "$RUN_DIR" "select-items" "failed" "$INPUT_COUNT" "null" \
    "$STARTED_AT" "$FINISHED_AT" "openai" "null" "$ERROR_MESSAGE"
fi
rm -f "$INPUT" "$OUTPUT" "$ERRORS"
exit "$STATUS"
