#!/usr/bin/env bash

# Shared utilities only. Pipeline stages retain their own required responsibilities.

PS04_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

ps04_now_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

ps04_die() {
  local exit_code="$1"
  shift
  printf 'error: %s\n' "$*" >&2
  exit "$exit_code"
}

ps04_require_command() {
  command -v "$1" >/dev/null 2>&1 || ps04_die 2 "required command not found: $1"
}

ps04_new_run_id() {
  python3 - <<'PY'
from datetime import datetime, timezone
from secrets import token_hex

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
print(f"{stamp}-{token_hex(3)}")
PY
}

ps04_previous_live_run_id() {
  python3 - "$PS04_ROOT/runs" <<'PY'
import json
import pathlib
import sys

runs = pathlib.Path(sys.argv[1])
found = []
if runs.exists():
    for path in runs.glob("*/run.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("mode") == "live" and isinstance(data.get("run_id"), str):
            found.append((str(data.get("started_at", "")), data["run_id"]))
print(max(found)[1] if found else "")
PY
}

ps04_validate_live_configuration() {
  python3 - "$PS04_ROOT" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
errors = []

def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing file: {path.relative_to(root)}")
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {path.relative_to(root)}: {exc}")
    return None

project = load_json(root / "config/project.json")
required_project = ("publication_name", "topic", "audience", "central_question")
if isinstance(project, dict):
    for key in required_project:
        if not isinstance(project.get(key), str) or not project[key].strip():
            errors.append(f"config/project.json requires nonempty string: {key}")
elif project is not None:
    errors.append("config/project.json must contain one JSON object")

sources = load_json(root / "config/sources.json")
required_source = ("source_id", "publisher_id", "kind", "url")
if isinstance(sources, list):
    if not sources:
        errors.append("config/sources.json must contain at least one source")
    seen = set()
    for index, source in enumerate(sources):
        label = f"config/sources.json[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in required_source:
            if not isinstance(source.get(key), str) or not source[key].strip():
                errors.append(f"{label} requires nonempty string: {key}")
        if source.get("kind") not in {"feed", "youtube", "podcast"}:
            errors.append(f"{label}.kind must be feed, youtube, or podcast")
        source_id = source.get("source_id")
        if isinstance(source_id, str):
            if source_id in seen:
                errors.append(f"duplicate source_id: {source_id}")
            seen.add(source_id)
elif sources is not None:
    errors.append("config/sources.json must contain a JSON array")

required_text = [
    "config/editorial_policy.md",
    "prompts/select_items.md",
    "prompts/create_briefs.md",
    "prompts/repair_brief.md",
    "prompts/write_articles.md",
    "prompts/write_video_scripts.md",
]
for relative in required_text:
    path = root / relative
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        errors.append(f"missing or empty required file: {relative}")

if errors:
    for error in errors:
        print(f"configuration error: {error}", file=sys.stderr)
    raise SystemExit(2)
PY
}

ps04_write_receipt() {
  local run_dir="$1"
  local stage="$2"
  local status="$3"
  local input_count="$4"
  local output_count="$5"
  local started_at="$6"
  local finished_at="$7"
  local tools_csv="$8"
  local cost_usd="$9"
  local error_message="${10:-}"

  python3 - "$run_dir" "$stage" "$status" "$input_count" "$output_count" \
    "$started_at" "$finished_at" "$tools_csv" "$cost_usd" "$error_message" <<'PY'
import json
import pathlib
import re
import sys
import uuid

run_dir = pathlib.Path(sys.argv[1])
stage, status = sys.argv[2], sys.argv[3]

def nullable_int(value):
    return None if value == "null" else int(value)

def nullable_cost(value):
    return None if value == "null" else float(value)

receipt = {
    "stage": stage,
    "status": status,
    "input_count": nullable_int(sys.argv[4]),
    "output_count": nullable_int(sys.argv[5]),
    "started_at": sys.argv[6],
    "finished_at": sys.argv[7],
    "tools_or_models": [value for value in sys.argv[8].split(",") if value],
    "cost_usd": nullable_cost(sys.argv[9]),
    "cost_is_estimate": False,
    "errors": [sys.argv[10]] if sys.argv[10] else [],
}

logs = run_dir / "logs"
logs.mkdir(parents=True, exist_ok=True)
safe_stage = re.sub(r"[^A-Za-z0-9_.-]+", "-", stage).strip("-") or "stage"
path = logs / f"{safe_stage}-{uuid.uuid4().hex[:12]}.json"
path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

ps04_assert_run_dir() {
  local candidate="$1"
  python3 - "$PS04_ROOT" "$candidate" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
candidate = pathlib.Path(sys.argv[2]).resolve()
runs = (root / "runs").resolve()
try:
    candidate.relative_to(runs)
except ValueError:
    print("error: package run directory must be inside runs/", file=sys.stderr)
    raise SystemExit(2)
if not candidate.is_dir():
    print(f"error: run directory not found: {candidate}", file=sys.stderr)
    raise SystemExit(2)
print(candidate)
PY
}
