#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

if [[ "$#" -ne 1 ]]; then
  printf 'usage: bash processing/filter_items.sh RUN_DIR < corpus.jsonl\n' >&2
  exit 2
fi

RUN_DIR="$1"
if [[ ! -d "$RUN_DIR" || ! -f "$RUN_DIR/run.json" ]]; then
  printf 'error: RUN_DIR must contain run.json: %s\n' "$RUN_DIR" >&2
  exit 2
fi

STARTED_AT="$(ps04_now_utc)"
ELIGIBLE_TEMP="$(mktemp "$RUN_DIR/.eligible.XXXXXX")" || exit 1
EXCLUSIONS_TEMP="$(mktemp "$RUN_DIR/.exclusions.XXXXXX")" || exit 1
COUNTS_TEMP="$(mktemp "$RUN_DIR/.filter-counts.XXXXXX")" || exit 1
INPUT_TEMP="$(mktemp "$RUN_DIR/.filter-input.XXXXXX")" || exit 1
cat >"$INPUT_TEMP"

python3 - "$RUN_DIR/run.json" "$ELIGIBLE_TEMP" "$EXCLUSIONS_TEMP" "$COUNTS_TEMP" "$INPUT_TEMP" <<'PY'
from datetime import date, datetime, timedelta
import json
import pathlib
import sys

run_path = pathlib.Path(sys.argv[1])
eligible_path = pathlib.Path(sys.argv[2])
exclusions_path = pathlib.Path(sys.argv[3])
counts_path = pathlib.Path(sys.argv[4])
input_path = pathlib.Path(sys.argv[5])

try:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    as_of = date.fromisoformat(run["as_of_date"])
except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
    print(f"invalid run metadata: {exc}", file=sys.stderr)
    raise SystemExit(2)

window_start = as_of - timedelta(days=29)
records = []
for line_number, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        print(f"malformed JSONL at line {line_number}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(record, dict):
        print(f"line {line_number} must contain a JSON object", file=sys.stderr)
        raise SystemExit(2)
    for field in ("item_id", "version_id", "published_at"):
        if field not in record:
            print(f"line {line_number} missing field: {field}", file=sys.stderr)
            raise SystemExit(2)
    records.append(record)

eligible = []
exclusions = []
for record in records:
    raw = record.get("published_at")
    reason = None
    detail = None
    if raw is None or raw == "":
        reason = "unknown_date"
        detail = "published_at is unknown"
    elif not isinstance(raw, str):
        reason = "invalid_date"
        detail = "published_at must be an ISO 8601 string or null"
    else:
        try:
            published_date = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                published_date = date.fromisoformat(raw)
            except ValueError:
                reason = "invalid_date"
                detail = f"published_at is not valid ISO 8601: {raw}"
        if reason is None:
            if published_date > as_of:
                reason = "future_date"
                detail = f"publication date {published_date.isoformat()} is after {as_of.isoformat()}"
            elif published_date < window_start:
                reason = "outside_window"
                detail = f"publication date {published_date.isoformat()} is before {window_start.isoformat()}"

    if reason is None:
        eligible.append(record)
    else:
        exclusions.append({
            "item_id": record["item_id"],
            "version_id": record["version_id"],
            "reason": reason,
            "detail": detail,
        })

with eligible_path.open("w", encoding="utf-8") as handle:
    for record in eligible:
        handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
with exclusions_path.open("w", encoding="utf-8") as handle:
    for record in exclusions:
        handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
counts_path.write_text(f"{len(records)} {len(eligible)} {len(exclusions)}\n", encoding="utf-8")
PY
STATUS=$?
FINISHED_AT="$(ps04_now_utc)"
if [[ "$STATUS" -ne 0 ]]; then
  rm -f "$ELIGIBLE_TEMP" "$EXCLUSIONS_TEMP" "$COUNTS_TEMP" "$INPUT_TEMP"
  ps04_write_receipt "$RUN_DIR" "filter-items" "failed" "null" "null" \
    "$STARTED_AT" "$FINISHED_AT" "python3" "0" "filtering failed"
  exit "$STATUS"
fi

read -r INPUT_COUNT ELIGIBLE_COUNT EXCLUDED_COUNT <"$COUNTS_TEMP"
mv "$EXCLUSIONS_TEMP" "$RUN_DIR/exclusions.jsonl"
ps04_write_receipt "$RUN_DIR" "filter-items" "completed" "$INPUT_COUNT" "$ELIGIBLE_COUNT" \
  "$STARTED_AT" "$FINISHED_AT" "python3" "0" ""
cat "$ELIGIBLE_TEMP"
rm -f "$ELIGIBLE_TEMP" "$COUNTS_TEMP" "$INPUT_TEMP"
