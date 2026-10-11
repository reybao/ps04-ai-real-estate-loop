#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

[[ "$#" -eq 1 ]] || ps04_die 2 "usage: bash content/write_video_scripts.sh RUN_DIR < briefs.jsonl"
RUN_DIR="$1"
[[ -f "$RUN_DIR/eligible.jsonl" ]] || ps04_die 2 "RUN_DIR must contain eligible.jsonl: $RUN_DIR"
STARTED_AT="$(ps04_now_utc)"
INPUT="$(mktemp "$RUN_DIR/.video-input.XXXXXX")" || exit 1
OUTPUT="$(mktemp "$RUN_DIR/.video-output.XXXXXX")" || exit 1
cat >"$INPUT"
INPUT_COUNT="$(awk 'NF {n += 1} END {print n + 0}' "$INPUT")"

python3 "$ROOT/content/write_video_scripts.py" "$RUN_DIR" "$INPUT" "$OUTPUT"
STATUS=$?
FINISHED_AT="$(ps04_now_utc)"
if [[ "$STATUS" -eq 0 ]]; then
  OUTPUT_COUNT="$(awk 'NF {n += 1} END {print n + 0}' "$OUTPUT")"
  MODEL="$(python3 - "$RUN_DIR/model/write-video-scripts.json" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1], encoding='utf-8'))
print(rows[0].get('model','openai') if rows else 'openai')
PY
)"
  ps04_write_receipt "$RUN_DIR" "write-video-scripts" "completed" "$INPUT_COUNT" "$OUTPUT_COUNT" \
    "$STARTED_AT" "$FINISHED_AT" "$MODEL" "null" ""
  cat "$OUTPUT"
else
  ps04_write_receipt "$RUN_DIR" "write-video-scripts" "failed" "$INPUT_COUNT" "null" \
    "$STARTED_AT" "$FINISHED_AT" "openai" "null" "video-script generation failed"
fi
rm -f "$INPUT" "$OUTPUT"
exit "$STATUS"
