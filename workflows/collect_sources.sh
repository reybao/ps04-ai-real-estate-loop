#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

if [[ "$#" -ne 1 ]]; then
  printf 'usage: bash workflows/collect_sources.sh RUN_DIR\n' >&2
  exit 2
fi
RUN_DIR="$1"
[[ -f "$RUN_DIR/run.json" ]] || ps04_die 2 "RUN_DIR must contain run.json: $RUN_DIR"
mkdir -p "$RUN_DIR/candidates" "$RUN_DIR/logs"

STARTED_AT="$(ps04_now_utc)"
OVERALL_STATUS=0
ERRORS=()

bash "$ROOT/collectors/fetch_feeds.sh" "$RUN_DIR" >"$RUN_DIR/candidates/feeds.jsonl"
FEED_STATUS=$?
bash "$ROOT/collectors/fetch_youtube.sh" "$RUN_DIR" >"$RUN_DIR/candidates/youtube.jsonl"
YOUTUBE_STATUS=$?
bash "$ROOT/collectors/fetch_podcasts.sh" "$RUN_DIR" >"$RUN_DIR/candidates/podcasts.jsonl"
PODCAST_STATUS=$?

for pair in "feeds:$FEED_STATUS" "youtube:$YOUTUBE_STATUS" "podcasts:$PODCAST_STATUS"; do
  name="${pair%%:*}"
  code="${pair##*:}"
  if [[ "$code" -ne 0 ]]; then
    OVERALL_STATUS=1
    ERRORS+=("$name collector exited $code")
  fi
done

cat "$RUN_DIR/candidates/feeds.jsonl" "$RUN_DIR/candidates/youtube.jsonl" "$RUN_DIR/candidates/podcasts.jsonl" \
  | tee "$RUN_DIR/candidates.jsonl" \
  | bash "$ROOT/processing/extract_content.sh" "$RUN_DIR" >"$RUN_DIR/items.jsonl"
PIPE_CODES=("${PIPESTATUS[@]}")
EXTRACT_STATUS="${PIPE_CODES[2]}"
if [[ "$EXTRACT_STATUS" -ne 0 ]]; then
  OVERALL_STATUS=1
  ERRORS+=("content extraction exited $EXTRACT_STATUS")
fi

if ! bash "$ROOT/data/store.sh" upsert "$RUN_DIR" <"$RUN_DIR/items.jsonl" >"$RUN_DIR/changes.jsonl"; then
  OVERALL_STATUS=1
  ERRORS+=("evidence upsert failed")
fi
if ! bash "$ROOT/data/store.sh" list >"$RUN_DIR/corpus.jsonl"; then
  OVERALL_STATUS=1
  ERRORS+=("evidence listing failed")
fi
if ! bash "$ROOT/processing/filter_items.sh" "$RUN_DIR" <"$RUN_DIR/corpus.jsonl" >"$RUN_DIR/eligible.jsonl"; then
  OVERALL_STATUS=1
  ERRORS+=("freshness filtering failed")
fi

FINISHED_AT="$(ps04_now_utc)"
INPUT_COUNT="$(awk 'NF {count += 1} END {print count + 0}' "$RUN_DIR/candidates.jsonl")"
OUTPUT_COUNT="$(awk 'NF {count += 1} END {print count + 0}' "$RUN_DIR/eligible.jsonl")"
ERROR_MESSAGE="$(IFS='; '; printf '%s' "${ERRORS[*]-}")"
if [[ "$OVERALL_STATUS" -eq 0 ]]; then
  RECEIPT_STATUS="completed"
else
  RECEIPT_STATUS="incomplete"
fi
ps04_write_receipt "$RUN_DIR" "collect-sources-workflow" "$RECEIPT_STATUS" "$INPUT_COUNT" "$OUTPUT_COUNT" \
  "$STARTED_AT" "$FINISHED_AT" "bash" "0" "$ERROR_MESSAGE"
exit "$OVERALL_STATUS"
