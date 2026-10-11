#!/usr/bin/env python3
"""Apply the snapshotted editorial policy to every eligible item."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from evidence_pack import item_excerpt, read_jsonl  # noqa: E402
from openai_request import OpenAIRequestError, request_json, write_metadata  # noqa: E402


def schema(expected_count: int) -> dict:
    score_properties = {
        name: {"type": "integer", "minimum": 0, "maximum": 2}
        for name in (
            "audience_relevance", "evidence_directness", "claim_specific_credibility",
            "novelty", "perspective_contribution",
        )
    }
    decision = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "item_id": {"type": "string"},
            "version_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["accept", "reject", "defer"]},
            "reason": {"type": "string"},
            "piece_ids": {
                "type": "array",
                "items": {"type": "string", "enum": ["01", "02", "03"]},
            },
            "scores": {
                "type": "object",
                "additionalProperties": False,
                "properties": score_properties,
                "required": list(score_properties),
            },
            "claim_cluster_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            },
            "uncertainties": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "item_id", "version_id", "decision", "reason", "piece_ids", "scores",
            "claim_cluster_id", "uncertainties",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"decisions": {
            "type": "array", "items": decision,
            "minItems": expected_count, "maxItems": expected_count,
        }},
        "required": ["decisions"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=pathlib.Path)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()

    items = read_jsonl(args.input)
    if not items:
        print("no eligible items were supplied for editorial selection", file=sys.stderr)
        return 1
    sources = json.loads((args.run_dir / "config/sources.json").read_text(encoding="utf-8"))
    source_by_id = {source["source_id"]: source for source in sources}
    packed = []
    for item in items:
        record = item_excerpt(item)
        source = source_by_id.get(item.get("source_id"), {})
        record["source_assessment"] = {
            "authority_tier": source.get("authority_tier"),
            "perspective": source.get("perspective"),
            "independence_note": source.get("independence_note"),
        }
        packed.append(record)

    base_payload = {
        "run": json.loads((args.run_dir / "run.json").read_text(encoding="utf-8")),
        "project": json.loads((args.run_dir / "config/project.json").read_text(encoding="utf-8")),
        "editorial_policy": (args.run_dir / "config/editorial_policy.md").read_text(encoding="utf-8"),
        "required_piece_questions": {
            "01": "What changed, and which developments matter most?",
            "02": "Which claims withstand scrutiny, and where are evidence or interpretations in tension?",
            "03": "What do the developments imply, and what should the audience watch next?",
        },
        "all_candidate_titles": [
            {"item_id": item["item_id"], "title": item["title"], "publisher_id": item["publisher_id"]}
            for item in items
        ],
    }
    instructions = (args.run_dir / "prompts/select_items.md").read_text(encoding="utf-8")
    decisions = []
    metadata_rows = []
    batch_size = 6
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        batch_number = start // batch_size + 1
        payload = {**base_payload, "items": packed[start:start + batch_size]}
        request_record = {
            "instructions": instructions,
            "input": payload,
            "schema_name": "ps04_editorial_decisions",
            "schema": schema(len(batch)),
        }
        request_path = args.run_dir / "model" / f"select-items-request-{batch_number:02d}.json"
        response_path = args.run_dir / "model" / f"select-items-batch-{batch_number:02d}.json"
        metadata_path = args.run_dir / "model" / f"select-items-batch-{batch_number:02d}-metadata.json"
        cached = None
        try:
            if request_path.is_file() and response_path.is_file():
                if json.loads(request_path.read_text(encoding="utf-8")) == request_record:
                    cached = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if isinstance(cached, list):
            batch_decisions = cached
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            else:
                metadata = {"model": "openai", "response_id": None, "status": "reused", "usage": None, "cost_usd": None}
        else:
            write_metadata(request_path, request_record)
            try:
                result, metadata = request_json(
                    instructions=instructions,
                    input_payload=payload,
                    schema_name="ps04_editorial_decisions",
                    schema=schema(len(batch)),
                    max_output_tokens=12000,
                )
            except OpenAIRequestError as exc:
                print(f"editorial selection failed in batch {batch_number}: {exc}", file=sys.stderr)
                return 1
            batch_decisions = result.get("decisions") if isinstance(result, dict) else None
            if isinstance(batch_decisions, list):
                write_metadata(response_path, batch_decisions)
                write_metadata(metadata_path, metadata)
        if not isinstance(batch_decisions, list) or len(batch_decisions) != len(batch):
            print(f"editorial selection batch {batch_number} did not return one decision per item", file=sys.stderr)
            return 1
        expected_by_id = {item["item_id"]: item for item in batch}
        returned_ids = [decision.get("item_id") for decision in batch_decisions]
        if len(set(returned_ids)) != len(batch) or set(returned_ids) != set(expected_by_id):
            print(f"editorial selection batch {batch_number} omitted or duplicated an item ID", file=sys.stderr)
            return 1
        normalized = []
        decisions_by_id = {decision["item_id"]: decision for decision in batch_decisions}
        for item in batch:
            decision = dict(decisions_by_id[item["item_id"]])
            # IDs are evidence-store metadata, never editorial judgments.
            decision["version_id"] = item["version_id"]
            normalized.append(decision)
        decisions.extend(normalized)
        metadata_rows.append({"batch": batch_number, **metadata})
    for expected, decision in zip(items, decisions):
        if (decision.get("item_id"), decision.get("version_id")) != (
            expected.get("item_id"), expected.get("version_id")
        ):
            print("editorial decisions are not in the same item/version order as input", file=sys.stderr)
            return 1
        piece_ids = decision.get("piece_ids", [])
        if decision.get("decision") == "accept" and not piece_ids:
            print(f"accepted item has no assigned piece: {decision.get('item_id')}", file=sys.stderr)
            return 1
        if decision.get("decision") != "accept" and piece_ids:
            print(f"non-accepted item has piece assignments: {decision.get('item_id')}", file=sys.stderr)
            return 1

    with args.output.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            handle.write(json.dumps(decision, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_metadata(
        args.run_dir / "model" / "select-items.json",
        {"model": metadata_rows[0]["model"], "batches": metadata_rows},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
