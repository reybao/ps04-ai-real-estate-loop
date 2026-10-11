#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

if [[ "$#" -ne 1 ]]; then
  printf 'usage: bash processing/extract_content.sh RUN_DIR < candidates.jsonl\n' >&2
  exit 2
fi
RUN_DIR="$1"
[[ -f "$RUN_DIR/run.json" ]] || ps04_die 2 "RUN_DIR must contain run.json: $RUN_DIR"

STARTED_AT="$(ps04_now_utc)"
INPUT_TEMP="$(mktemp "$RUN_DIR/.extract-input.XXXXXX")" || exit 1
OUTPUT_TEMP="$(mktemp "$RUN_DIR/.extract-output.XXXXXX")" || exit 1
ERRORS_TEMP="$(mktemp "$RUN_DIR/.extract-errors.XXXXXX")" || exit 1
COUNTS_TEMP="$(mktemp "$RUN_DIR/.extract-counts.XXXXXX")" || exit 1
METADATA_TEMP="$(mktemp "$RUN_DIR/.extract-metadata.XXXXXX")" || exit 1
cat >"$INPUT_TEMP"

python3 "$ROOT/processing/extract_content.py" \
  --input "$INPUT_TEMP" --output "$OUTPUT_TEMP" --errors "$ERRORS_TEMP" --counts "$COUNTS_TEMP" \
  --metadata "$METADATA_TEMP"
STATUS=$?
FINISHED_AT="$(ps04_now_utc)"
if [[ -s "$COUNTS_TEMP" ]]; then
  read -r INPUT_COUNT OUTPUT_COUNT ERROR_COUNT <"$COUNTS_TEMP"
else
  INPUT_COUNT=null
  OUTPUT_COUNT=null
  ERROR_COUNT=null
fi

ERROR_MESSAGE=""
if [[ "${ERROR_COUNT:-0}" != "null" && "${ERROR_COUNT:-0}" -gt 0 ]]; then
  ERROR_MESSAGE="$(python3 - "$ERRORS_TEMP" <<'PY'
import json,sys
try:
 data=json.load(open(sys.argv[1],encoding='utf-8'))
 print('; '.join(f"{x.get('item_id')}: {x.get('error')}" for x in data[:10]))
except Exception:
 print('unable to read extraction errors')
PY
)"
  cp "$ERRORS_TEMP" "$RUN_DIR/extraction_errors.json"
fi

if [[ "$STATUS" -eq 0 ]]; then
  RECEIPT_STATUS="completed"
elif [[ "${OUTPUT_COUNT:-0}" != "null" && "${OUTPUT_COUNT:-0}" -gt 0 ]]; then
  RECEIPT_STATUS="incomplete"
else
  RECEIPT_STATUS="failed"
fi
TOOLS="python3"
COST="0"
MEDIA_GAP_COUNT="0"
if [[ -s "$METADATA_TEMP" ]]; then
  read -r TOOLS COST MEDIA_GAP_COUNT < <(python3 - "$METADATA_TEMP" <<'PY'
import json,sys
data=json.load(open(sys.argv[1], encoding='utf-8'))
print(','.join(data.get('tools_or_models', [])), 'null' if data.get('cost_usd') is None else data['cost_usd'], data.get('media_gap_count', 0))
PY
)
  cp "$METADATA_TEMP" "$RUN_DIR/extraction_metadata.json"
fi
if [[ "$MEDIA_GAP_COUNT" -gt 0 ]]; then
  ERROR_MESSAGE="${ERROR_MESSAGE:+$ERROR_MESSAGE; }${MEDIA_GAP_COUNT} YouTube media download(s) failed; captions retained."
  if [[ "$RECEIPT_STATUS" == "completed" ]]; then
    RECEIPT_STATUS="incomplete"
  fi
fi
ps04_write_receipt "$RUN_DIR" "extract-content" "$RECEIPT_STATUS" "$INPUT_COUNT" "$OUTPUT_COUNT" \
  "$STARTED_AT" "$FINISHED_AT" "$TOOLS" "$COST" "$ERROR_MESSAGE"

cat "$OUTPUT_TEMP"
rm -f "$INPUT_TEMP" "$OUTPUT_TEMP" "$ERRORS_TEMP" "$COUNTS_TEMP" "$METADATA_TEMP"
exit "$STATUS"
