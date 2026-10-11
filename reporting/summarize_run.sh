#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"

if [[ "$#" -ne 1 ]]; then
  printf 'usage: bash reporting/summarize_run.sh RUN_DIR\n' >&2
  exit 2
fi

RUN_DIR="$1"
if [[ ! -d "$RUN_DIR" || ! -f "$RUN_DIR/run.json" ]]; then
  printf 'error: RUN_DIR must contain run.json: %s\n' "$RUN_DIR" >&2
  exit 2
fi

STARTED_AT="$(ps04_now_utc)"
TEMPORARY="$(mktemp "$RUN_DIR/.summary-output.XXXXXX")" || exit 1

if ! python3 - "$RUN_DIR" "$ROOT" >"$TEMPORARY" <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import json
import pathlib
import sys

run_dir = pathlib.Path(sys.argv[1])
project_root = pathlib.Path(sys.argv[2])

def read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

def read_jsonl(path: pathlib.Path):
    records = []
    if not path.exists():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return None
    return records

def count_records(name):
    records = read_jsonl(run_dir / name)
    return None if records is None else len(records)

def count_value(name, field, value):
    records = read_jsonl(run_dir / name)
    if records is None:
        return None
    return sum(1 for record in records if record.get(field) == value)

run = read_json(run_dir / "run.json")
if not isinstance(run, dict):
    print("invalid run.json", file=sys.stderr)
    raise SystemExit(1)

receipts = []
for path in sorted((run_dir / "logs").glob("*.json")) if (run_dir / "logs").exists() else []:
    receipt = read_json(path)
    if isinstance(receipt, dict):
        receipts.append((path, receipt))

failed_stages = []
incomplete_stages = []
tools = set()
known_cost = 0.0
unknown_cost = False
latest_finish = None
latest_by_stage = {}
for path, receipt in receipts:
    stage = receipt.get("stage")
    if isinstance(stage, str):
        rank = (str(receipt.get("finished_at") or ""), path.stat().st_mtime_ns, path.name)
        if stage not in latest_by_stage or rank > latest_by_stage[stage][0]:
            latest_by_stage[stage] = (rank, receipt)
    for tool in receipt.get("tools_or_models") or []:
        if isinstance(tool, str):
            tools.add(tool)
    cost = receipt.get("cost_usd")
    if isinstance(cost, (int, float)):
        known_cost += float(cost)
    else:
        unknown_cost = True
    finished = receipt.get("finished_at")
    if isinstance(finished, str):
        latest_finish = max(latest_finish or finished, finished)

for stage, (_, receipt) in latest_by_stage.items():
    if receipt.get("status") == "failed":
        failed_stages.append(stage)
    if receipt.get("status") in {"incomplete", "partial"}:
        incomplete_stages.append(stage)

candidates = read_jsonl(run_dir / "candidates.jsonl")
items = read_jsonl(run_dir / "items.jsonl")
eligible = read_jsonl(run_dir / "eligible.jsonl")
coverage = {"basis": "eligible_items", "kinds": {}, "independent_publishers": []}
duplicate_observations = None
if candidates is not None:
    identities = [(record.get("item_id"), record.get("url")) for record in candidates]
    duplicate_observations = len(identities) - len(set(identities))
if eligible is not None:
    # Discovery counts remain visible above, but only distinct, in-window items
    # with retained evidence can contribute to substantive source coverage.
    distinct = {record.get("item_id"): record for record in eligible if isinstance(record.get("item_id"), str)}
    for record in distinct.values():
        kind = record.get("kind")
        if isinstance(kind, str):
            coverage["kinds"][kind] = coverage["kinds"].get(kind, 0) + 1
    coverage["independent_publishers"] = sorted({
        record["publisher_id"] for record in distinct.values()
        if isinstance(record.get("publisher_id"), str)
    })

youtube_media = {"video_retained": 0, "audio_retained": 0, "transcript_only": 0}
if items is not None:
    for item in items:
        if item.get("kind") != "youtube":
            continue
        raw = item.get("raw_path")
        media_file = project_root / raw if isinstance(raw, str) and raw else None
        has_video = bool(media_file and media_file.is_file() and item.get("media_status") == "video_retained")
        has_audio = bool(media_file and media_file.is_file() and item.get("media_status") == "audio_retained")
        if has_video:
            youtube_media["video_retained"] += 1
        elif has_audio:
            youtube_media["audio_retained"] += 1
        else:
            youtube_media["transcript_only"] += 1

review = read_json(run_dir / "review.json")
approval = read_json(run_dir / "approval.json")
package_manifest = read_json(run_dir / "package/manifest.json")
article_count = count_records("articles.jsonl")
video_count = count_records("video_scripts.jsonl")

ready = (
    isinstance(package_manifest, dict)
    and isinstance(review, dict)
    and review.get("passed") is True
    and package_manifest.get("review_id") == review.get("review_id")
    and isinstance(approval, dict)
    and approval.get("decision") == "approve"
    and approval.get("review_id") == review.get("review_id")
)
drafts_complete = article_count == 3 and video_count == 3 and isinstance(review, dict)
reviewed_drafts_complete = drafts_complete and review.get("passed") is True
if reviewed_drafts_complete:
    # Earlier orchestration failures are superseded by complete, checked artifacts.
    failed_stages = [stage for stage in failed_stages if stage not in {"run", "create-series-workflow"}]
if ready:
    status = "ready_for_production"
elif reviewed_drafts_complete and not failed_stages:
    status = "awaiting_review"
else:
    status = "failed"

remaining = []
if status == "failed":
    remaining.append("Repair failed or incomplete stages and rerun the affected component.")
elif status == "awaiting_review":
    remaining.extend([
        "Inspect the logged collection/extraction gaps; only eligible retained evidence was used in the drafts.",
        "Review the actual evidence, decisions, briefs, article drafts, and video scripts.",
        "Record corrections and create approval.json with the current review_id.",
        f"Run bash run.sh --package runs/{run.get('run_id')} after approval.",
    ])
else:
    remaining.extend([
        "Produce the three videos in Google Vids or HeyGen.",
        "Publish the articles and videos, then fill publication_links.json.",
    ])
if youtube_media["transcript_only"]:
    remaining.append(
        "YouTube items with captions only lack a retained video/audio download; repair or disclose this coverage gap."
    )

started = run.get("started_at")
elapsed_seconds = None
try:
    start_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    end_value = latest_finish or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
    elapsed_seconds = max(0, int((end_dt - start_dt).total_seconds()))
except (TypeError, ValueError):
    pass

summary = {
    "run_id": run.get("run_id"),
    "status": status,
    "as_of_date": run.get("as_of_date"),
    "previous_run_id": run.get("previous_run_id"),
    "counts": {
        "discovered": count_records("candidates.jsonl"),
        "duplicate_observations": duplicate_observations,
        "extracted": count_records("items.jsonl"),
        "new": count_value("changes.jsonl", "change", "new"),
        "changed": count_value("changes.jsonl", "change", "changed"),
        "unchanged": count_value("changes.jsonl", "change", "unchanged"),
        "eligible": count_records("eligible.jsonl"),
        "excluded": count_records("exclusions.jsonl"),
        "accepted": count_value("decisions.jsonl", "decision", "accept"),
        "rejected": count_value("decisions.jsonl", "decision", "reject"),
        "deferred": count_value("decisions.jsonl", "decision", "defer"),
        "articles": article_count,
        "video_scripts": video_count,
    },
    "source_coverage": coverage,
    "youtube_media": youtube_media,
    "failed_stages": sorted(set(failed_stages)),
    "incomplete_stages": sorted(set(incomplete_stages)),
    "elapsed_seconds": elapsed_seconds,
    "tools_or_models": sorted(tools),
    "cost_usd_known": round(known_cost, 6),
    "has_unknown_costs": unknown_cost,
    "remaining_manual_actions": remaining,
}
print(json.dumps(summary, indent=2, ensure_ascii=False))
PY
then
  rm -f "$TEMPORARY"
  FINISHED_AT="$(ps04_now_utc)"
  ps04_write_receipt "$RUN_DIR" "summarize-run" "failed" "null" "null" \
    "$STARTED_AT" "$FINISHED_AT" "python3" "0" "summary generation failed"
  exit 1
fi

FINISHED_AT="$(ps04_now_utc)"
ps04_write_receipt "$RUN_DIR" "summarize-run" "completed" "null" "1" \
  "$STARTED_AT" "$FINISHED_AT" "python3" "0" ""
cat "$TEMPORARY"
rm -f "$TEMPORARY"
