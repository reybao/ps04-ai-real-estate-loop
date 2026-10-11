#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

[[ "$#" -eq 1 ]] || ps04_die 2 "usage: bash editorial/create_briefs.sh RUN_DIR < decisions.jsonl"
RUN_DIR="$1"
[[ -f "$RUN_DIR/eligible.jsonl" ]] || ps04_die 2 "RUN_DIR must contain eligible.jsonl: $RUN_DIR"

STARTED_AT="$(ps04_now_utc)"
INPUT="$(mktemp "$RUN_DIR/.brief-input.XXXXXX")" || exit 1
OUTPUT="$(mktemp "$RUN_DIR/.brief-output.XXXXXX")" || exit 1
cat >"$INPUT"
INPUT_COUNT="$(awk 'NF {n += 1} END {print n + 0}' "$INPUT")"

python3 "$ROOT/editorial/create_briefs.py" "$RUN_DIR" "$INPUT" "$OUTPUT"
STATUS=$?
FINISHED_AT="$(ps04_now_utc)"
if [[ "$STATUS" -eq 0 ]]; then
  OUTPUT_COUNT="$(awk 'NF {n += 1} END {print n + 0}' "$OUTPUT")"
  MODEL="$(python3 - "$RUN_DIR/model/create-briefs.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1], encoding='utf-8')).get('model','openai'))
PY
)"
  ps04_write_receipt "$RUN_DIR" "create-briefs" "completed" "$INPUT_COUNT" "$OUTPUT_COUNT" \
    "$STARTED_AT" "$FINISHED_AT" "$MODEL" "null" ""
  cat "$OUTPUT"
else
  ps04_write_receipt "$RUN_DIR" "create-briefs" "failed" "$INPUT_COUNT" "null" \
    "$STARTED_AT" "$FINISHED_AT" "openai" "null" "brief creation or evidence validation failed"
fi
rm -f "$INPUT" "$OUTPUT"
exit "$STATUS"
