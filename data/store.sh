#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

DB_PATH="${PS04_EVIDENCE_DB:-$ROOT/data/evidence/store.sqlite3}"

usage() {
  cat >&2 <<'EOF'
Usage:
  bash data/store.sh init
  bash data/store.sh upsert RUN_DIR < items.jsonl
  bash data/store.sh list
  bash data/store.sh get ITEM_ID [VERSION_ID]
EOF
}

initialize_store() {
  python3 - "$DB_PATH" <<'PY'
import pathlib
import sqlite3
import sys

path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
connection = sqlite3.connect(path)
try:
    connection.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            latest_version_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS versions (
            item_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            record_json TEXT NOT NULL,
            first_seen_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (item_id, version_id),
            FOREIGN KEY (item_id) REFERENCES items(item_id)
        );
        CREATE TABLE IF NOT EXISTS observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            change_kind TEXT NOT NULL CHECK(change_kind IN ('new', 'changed', 'unchanged')),
            FOREIGN KEY (item_id, version_id) REFERENCES versions(item_id, version_id)
        );
        CREATE INDEX IF NOT EXISTS observations_run_idx ON observations(run_id);
    """)
    connection.commit()
finally:
    connection.close()
PY
}

upsert_items() {
  local run_dir="$1"
  [[ -f "$run_dir/run.json" ]] || ps04_die 2 "RUN_DIR must contain run.json: $run_dir"
  initialize_store || return 1

  local started_at finished_at temporary input_temporary status input_count output_count
  started_at="$(ps04_now_utc)"
  temporary="$(mktemp "$run_dir/.changes.XXXXXX")" || return 1
  input_temporary="$(mktemp "$run_dir/.store-input.XXXXXX")" || return 1
  cat >"$input_temporary"

  python3 - "$DB_PATH" "$run_dir/run.json" "$input_temporary" >"$temporary" <<'PY'
from datetime import datetime, timezone
import json
import pathlib
import sqlite3
import sys

db_path = pathlib.Path(sys.argv[1])
run_path = pathlib.Path(sys.argv[2])
input_path = pathlib.Path(sys.argv[3])
try:
    run = json.loads(run_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"invalid run metadata: {exc}", file=sys.stderr)
    raise SystemExit(2)
run_id = run.get("run_id")
if not isinstance(run_id, str) or not run_id:
    print("run.json requires a nonempty run_id", file=sys.stderr)
    raise SystemExit(2)

required = {
    "item_id", "source_id", "publisher_id", "kind", "title", "url",
    "published_at", "retrieved_at", "media_url", "version_id",
    "text_path", "segments_path",
}
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
    missing = sorted(required - record.keys())
    if missing:
        print(f"line {line_number} missing fields: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(record.get("item_id"), str) or not record["item_id"]:
        print(f"line {line_number} has invalid item_id", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(record.get("version_id"), str) or not record["version_id"]:
        print(f"line {line_number} has invalid version_id", file=sys.stderr)
        raise SystemExit(2)
    records.append(record)

connection = sqlite3.connect(db_path)
connection.execute("PRAGMA foreign_keys = ON")
changes = []
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
try:
    connection.execute("BEGIN IMMEDIATE")
    for record in records:
        item_id = record["item_id"]
        version_id = record["version_id"]
        item_row = connection.execute(
            "SELECT latest_version_id FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()
        version_row = connection.execute(
            "SELECT 1 FROM versions WHERE item_id = ? AND version_id = ?",
            (item_id, version_id),
        ).fetchone()

        if item_row is None:
            change = "new"
            connection.execute(
                "INSERT INTO items(item_id, latest_version_id) VALUES (?, ?)",
                (item_id, version_id),
            )
            connection.execute(
                "INSERT INTO versions(item_id, version_id, record_json, first_seen_run_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (item_id, version_id, json.dumps(record, separators=(",", ":"), ensure_ascii=False), run_id, now),
            )
        elif version_row is not None:
            change = "unchanged"
        else:
            change = "changed"
            connection.execute(
                "INSERT INTO versions(item_id, version_id, record_json, first_seen_run_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (item_id, version_id, json.dumps(record, separators=(",", ":"), ensure_ascii=False), run_id, now),
            )
            connection.execute(
                "UPDATE items SET latest_version_id = ? WHERE item_id = ?",
                (version_id, item_id),
            )

        connection.execute(
            "INSERT INTO observations(item_id, version_id, run_id, observed_at, change_kind) VALUES (?, ?, ?, ?, ?)",
            (item_id, version_id, run_id, now, change),
        )
        changes.append({"item_id": item_id, "version_id": version_id, "change": change})
    connection.commit()
except Exception:
    connection.rollback()
    raise
finally:
    connection.close()

for change in changes:
    print(json.dumps(change, separators=(",", ":"), ensure_ascii=False))
PY
  status=$?
  finished_at="$(ps04_now_utc)"
  if [[ "$status" -ne 0 ]]; then
    rm -f "$temporary" "$input_temporary"
    ps04_write_receipt "$run_dir" "store-upsert" "failed" "null" "null" \
      "$started_at" "$finished_at" "python3,sqlite3" "0" "upsert failed"
    return "$status"
  fi

  output_count="$(awk 'NF {count += 1} END {print count + 0}' "$temporary")"
  input_count="$output_count"
  ps04_write_receipt "$run_dir" "store-upsert" "completed" "$input_count" "$output_count" \
    "$started_at" "$finished_at" "python3,sqlite3" "0" ""
  cat "$temporary"
  rm -f "$temporary" "$input_temporary"
}

list_items() {
  [[ -f "$DB_PATH" ]] || return 0
  python3 - "$DB_PATH" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
try:
    rows = connection.execute("""
        SELECT versions.record_json
        FROM items
        JOIN versions
          ON versions.item_id = items.item_id
         AND versions.version_id = items.latest_version_id
        ORDER BY items.item_id
    """)
    for (record_json,) in rows:
        print(record_json)
finally:
    connection.close()
PY
}

get_item() {
  local item_id="$1"
  local version_id="${2:-}"
  [[ -f "$DB_PATH" ]] || {
    printf 'error: evidence store is not initialized\n' >&2
    return 1
  }
  python3 - "$DB_PATH" "$item_id" "$version_id" <<'PY'
import sqlite3
import sys

db_path, item_id, version_id = sys.argv[1:4]
connection = sqlite3.connect(db_path)
try:
    if version_id:
        row = connection.execute(
            "SELECT record_json FROM versions WHERE item_id = ? AND version_id = ?",
            (item_id, version_id),
        ).fetchone()
    else:
        row = connection.execute("""
            SELECT versions.record_json
            FROM items
            JOIN versions
              ON versions.item_id = items.item_id
             AND versions.version_id = items.latest_version_id
            WHERE items.item_id = ?
        """, (item_id,)).fetchone()
    if row is None:
        print(f"error: evidence item not found: {item_id}", file=sys.stderr)
        raise SystemExit(1)
    print(row[0])
finally:
    connection.close()
PY
}

ps04_require_command python3
case "${1:-}" in
  init)
    [[ "$#" -eq 1 ]] || { usage; exit 2; }
    initialize_store
    ;;
  upsert)
    [[ "$#" -eq 2 ]] || { usage; exit 2; }
    upsert_items "$2"
    ;;
  list)
    [[ "$#" -eq 1 ]] || { usage; exit 2; }
    list_items
    ;;
  get)
    [[ "$#" -eq 2 || "$#" -eq 3 ]] || { usage; exit 2; }
    get_item "$2" "${3:-}"
    ;;
  *)
    usage
    exit 2
    ;;
esac
