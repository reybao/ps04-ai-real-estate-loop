#!/usr/bin/env python3
"""Create and validate three claim-level editorial briefs."""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from evidence_pack import evidence_index, item_excerpt, read_jsonl, resolve_locator  # noqa: E402
from openai_request import OpenAIRequestError, request_json, write_metadata  # noqa: E402


def schema() -> dict:
    text_locator = {
        "type": "object", "additionalProperties": False,
        "properties": {"type": {"type": "string", "enum": ["text"]}, "quote": {"type": "string"}},
        "required": ["type", "quote"],
    }


    segment_locator = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "type": {"type": "string", "enum": ["segment"]},
            "segment_id": {"type": "string"},
        },
        "required": ["type", "segment_id"],
    }
    reference = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "item_id": {"type": "string"},
            "version_id": {"type": "string"},
            "locator": {"anyOf": [text_locator, segment_locator]},
        },
        "required": ["item_id", "version_id", "locator"],
    }
    claim = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string"},
            "statement": {"type": "string"},
            "type": {"type": "string", "enum": ["reported_fact", "source_claim", "inference"]},
            "evidence": {"type": "array", "items": reference},
        },
        "required": ["claim_id", "statement", "type", "evidence"],
    }
    brief = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "piece_id": {"type": "string", "enum": ["01", "02", "03"]},
            "title": {"type": "string"},
            "question": {"type": "string"},
            "argument": {"type": "string"},
            "synthesis": {"type": "string"},
            "limitations": {"type": "string"},
            "claims": {"type": "array", "items": claim},
        },
        "required": ["piece_id", "title", "question", "argument", "synthesis", "limitations", "claims"],
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {"briefs": {"type": "array", "items": brief, "minItems": 3, "maxItems": 3}},
        "required": ["briefs"],
    }


def align_text_quote(reference: dict, item: dict) -> str | None:
    """Snap a nearly exact model quote to a retained source sentence."""
    locator = reference.get("locator", {})
    if locator.get("type") != "text" or not isinstance(locator.get("quote"), str):
        return None
    path = ROOT / item["text_path"]
    text = path.read_text(encoding="utf-8")
    quote = locator["quote"].strip()
    if quote in text:
        return None
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if len(part.strip()) >= 20]
    if not sentences:
        return None
    match = max(sentences, key=lambda part: difflib.SequenceMatcher(None, quote, part).ratio())
    similarity = difflib.SequenceMatcher(None, quote, match).ratio()
    if similarity < 0.9:
        return None
    locator["quote"] = match
    return quote


def apply_logged_curation(result: dict, path: pathlib.Path) -> dict:
    """Apply explicit, reviewable human corrections to an immutable model response."""
    if not path.is_file():
        return result
    curated = json.loads(json.dumps(result))
    operations = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(operations, list):
        raise ValueError("brief curation must be an array of operations")
    for operation in operations:
        if not isinstance(operation, dict) or not operation.get("reason"):
            raise ValueError("each brief curation operation needs a reason")
        claims = [
            claim
            for brief in curated["briefs"] if brief["piece_id"] == operation["piece_id"]
            for claim in brief["claims"] if claim["claim_id"] == operation["claim_id"]
        ]
        if len(claims) != 1:
            raise ValueError("brief curation claim is not unique")
        claim = claims[0]
        kind = operation.get("type")
        if kind == "replace_segment":
            matches = [
                ref for ref in claim["evidence"]
                if ref["item_id"] == operation["item_id"]
                and ref["locator"] == {"type": "segment", "segment_id": operation["from"]}
            ]
            if len(matches) != 1:
                raise ValueError("brief curation segment reference is not unique")
            matches[0]["locator"]["segment_id"] = operation["to"]
        elif kind == "append_evidence":
            claim["evidence"].append(operation["reference"])
        elif kind == "replace_statement":
            if claim["statement"] != operation["from"]:
                raise ValueError("brief curation original statement changed")
            claim["statement"] = operation["to"]
        else:
            raise ValueError(f"unknown brief curation operation: {kind}")
    return curated


def brief_issue(brief: dict, accepted_keys: set[tuple[str, str]], items_by_key: dict) -> str | None:
    """Check one model brief before accepting it or requesting a targeted repair."""
    piece_id = brief.get("piece_id", "unknown")
    claims = brief.get("claims")
    if not isinstance(claims, list) or not claims:
        return f"piece {piece_id} has no claims"
    publishers: set[str] = set()
    for claim_number, claim in enumerate(claims, 1):
        evidence = claim.get("evidence") if isinstance(claim, dict) else None
        if not isinstance(evidence, list) or not evidence:
            return f"piece {piece_id} claim {claim_number} has no evidence"
        for reference in evidence:
            if not isinstance(reference, dict):
                return f"piece {piece_id} claim {claim_number} has a malformed reference"
            key = (reference.get("item_id"), reference.get("version_id"))
            if key not in accepted_keys:
                return f"piece {piece_id} claim {claim_number} cites evidence that was not accepted"
            item = items_by_key.get(key)
            if item is None:
                return f"piece {piece_id} claim {claim_number} cites evidence outside the eligible set"
            # Probe a copy so the final normalization log still records the model's original quote.
            probe = copy.deepcopy(reference)
            align_text_quote(probe, item)
            error = resolve_locator(probe, items_by_key)
            if error:
                return f"piece {piece_id} claim {claim_number} has unresolved evidence: {error}"
            publishers.add(item["publisher_id"])
    if len(publishers) < 3:
        return f"piece {piece_id} uses only {len(publishers)} independent publishers; three are required"
    return None


def single_brief_schema(piece_id: str) -> dict:
    brief = copy.deepcopy(schema()["properties"]["briefs"]["items"])
    brief["properties"]["piece_id"]["enum"] = [piece_id]
    return {
        "type": "object", "additionalProperties": False,
        "properties": {"brief": brief}, "required": ["brief"],
    }


def repair_briefs(
    run_dir: pathlib.Path,
    briefs: list[dict],
    accepted_keys: set[tuple[str, str]],
    items_by_key: dict,
    accepted_evidence: list[dict],
    project: dict,
    editorial_policy: str,
) -> bool:
    """Retry only invalid briefs, twice at most, without re-collecting evidence."""
    log_path = run_dir / "model" / "create-briefs-repair-log.json"
    repair_log: list[dict] = []
    available_publishers = {item["publisher_id"] for item in accepted_evidence}
    for index, brief in enumerate(briefs):
        issue = brief_issue(brief, accepted_keys, items_by_key)
        if issue is None:
            continue
        piece_id = brief["piece_id"]
        if len(available_publishers) < 3:
            print(
                f"{issue}; only {len(available_publishers)} accepted independent publishers "
                "are available, so editorial selection or collection must be revisited",
                file=sys.stderr,
            )
            return False

        prompt_path = run_dir / "prompts" / "repair_brief.md"
        if not prompt_path.is_file():
            # Older runs did not snapshot this new prompt. Preserve the exact recovery
            # instructions in their run directory before the first repair request.
            prompt_path.write_text(
                (ROOT / "prompts" / "repair_brief.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        instructions = prompt_path.read_text(encoding="utf-8")
        current = brief
        for attempt in range(1, 3):
            prefix = f"create-briefs-piece-{piece_id}-retry-{attempt:02d}"
            request_path = run_dir / "model" / f"{prefix}-request.json"
            response_path = run_dir / "model" / f"{prefix}-raw.json"
            metadata_path = run_dir / "model" / f"{prefix}-metadata.json"
            request_record = {
                "instructions": instructions,
                "input": {
                    "project": project,
                    "editorial_policy": editorial_policy,
                    "piece_id": piece_id,
                    "previous_brief": current,
                    "validation_error": issue,
                    "accepted_evidence": accepted_evidence,
                    "hard_requirements": [
                        "Cite at least three independent publisher_id values in this piece.",
                        "Use only accepted item/version pairs and resolvable exact locators.",
                        "Do not add a source unless it actually supports the cited claim.",
                    ],
                },
                "schema_name": "ps04_repaired_editorial_brief",
                "schema": single_brief_schema(piece_id),
            }
            if request_path.is_file():
                if json.loads(request_path.read_text(encoding="utf-8")) != request_record:
                    print(f"saved retry request differs from current inputs: {request_path}", file=sys.stderr)
                    return False
            else:
                if response_path.exists():
                    print(f"retry response has no saved request: {response_path}", file=sys.stderr)
                    return False
                write_metadata(request_path, request_record)
            reused = response_path.is_file()
            if reused:
                response = json.loads(response_path.read_text(encoding="utf-8"))
            else:
                try:
                    response, metadata = request_json(
                        instructions=instructions,
                        input_payload=request_record["input"],
                        schema_name=request_record["schema_name"],
                        schema=request_record["schema"],
                        max_output_tokens=10000,
                    )
                except OpenAIRequestError as exc:
                    repair_log.append({
                        "piece_id": piece_id, "attempt": attempt, "input_error": issue,
                        "request_path": str(request_path.relative_to(run_dir)),
                        "status": "api_failed", "error": str(exc),
                    })
                    write_metadata(log_path, repair_log)
                    print(f"brief {piece_id} repair request failed: {exc}", file=sys.stderr)
                    return False
                write_metadata(response_path, response)
                write_metadata(metadata_path, metadata)

            candidate = response.get("brief") if isinstance(response, dict) else None
            if not isinstance(candidate, dict) or candidate.get("piece_id") != piece_id:
                next_issue = f"repair response must contain only piece {piece_id}"
            else:
                next_issue = brief_issue(candidate, accepted_keys, items_by_key)
            repair_log.append({
                "piece_id": piece_id, "attempt": attempt, "input_error": issue,
                "request_path": str(request_path.relative_to(run_dir)),
                "response_path": str(response_path.relative_to(run_dir)),
                "metadata_path": str(metadata_path.relative_to(run_dir)),
                "status": "reused" if reused else "requested",
                "validation_error": next_issue,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            write_metadata(log_path, repair_log)
            if next_issue is None:
                briefs[index] = candidate
                break
            if isinstance(candidate, dict) and candidate.get("piece_id") == piece_id:
                current = candidate
            issue = next_issue
        else:
            print(f"brief {piece_id} still fails after two targeted repairs: {issue}", file=sys.stderr)
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=pathlib.Path)
    parser.add_argument("decisions", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()

    decisions = read_jsonl(args.decisions)
    eligible = read_jsonl(args.run_dir / "eligible.jsonl")
    items_by_key = evidence_index(eligible)
    accepted = [decision for decision in decisions if decision.get("decision") == "accept"]
    accepted_keys = {(row.get("item_id"), row.get("version_id")) for row in accepted}
    assignments = {
        (row.get("item_id"), row.get("version_id")): set(row.get("piece_ids", []))
        for row in accepted
    }
    if len(accepted_keys) < 3:
        print("at least three accepted evidence items are required to create briefs", file=sys.stderr)
        return 1
    item_payload = []
    for decision in accepted:
        item = items_by_key.get((decision["item_id"], decision["version_id"]))
        if item is None:
            print(f"accepted decision does not resolve: {decision['item_id']}", file=sys.stderr)
            return 1
        packed = item_excerpt(item, text_limit=10000, segment_limit=120)
        packed["editorial_assignment"] = {
            "piece_ids": decision["piece_ids"],
            "reason": decision["reason"],
            "uncertainties": decision.get("uncertainties", []),
        }
        item_payload.append(packed)

    payload = {
        "run": json.loads((args.run_dir / "run.json").read_text(encoding="utf-8")),
        "project": json.loads((args.run_dir / "config/project.json").read_text(encoding="utf-8")),
        "editorial_policy": (args.run_dir / "config/editorial_policy.md").read_text(encoding="utf-8"),
        "accepted_evidence": item_payload,
        "hard_requirements": [
            "Exactly three briefs with IDs 01, 02, and 03.",
            "Each brief must cite at least three independent publisher_id values.",
            "Across the series, feed, YouTube, and podcast evidence must all be used.",
            "Use only exact quotes and supplied transcript segment IDs.",
        ],
    }
    instructions = (args.run_dir / "prompts/create_briefs.md").read_text(encoding="utf-8")
    request_record = {
        "instructions": instructions, "input": payload,
        "schema_name": "ps04_editorial_briefs", "schema": schema(),
    }
    request_path = args.run_dir / "model" / "create-briefs-request.json"
    response_path = args.run_dir / "model" / "create-briefs-raw.json"
    metadata_path = args.run_dir / "model" / "create-briefs-metadata.json"
    result = None
    try:
        if request_path.is_file() and response_path.is_file():
            if json.loads(request_path.read_text(encoding="utf-8")) == request_record:
                result = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result = None
    if result is not None:
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file()
            else {"model": "openai", "response_id": None, "status": "reused", "usage": None, "cost_usd": None}
        )
    else:
        write_metadata(request_path, request_record)
        try:
            result, metadata = request_json(
                instructions=instructions,
                input_payload=payload,
                schema_name="ps04_editorial_briefs",
                schema=schema(),
                max_output_tokens=26000,
            )
        except OpenAIRequestError as exc:
            print(f"brief creation failed: {exc}", file=sys.stderr)
            return 1
        write_metadata(response_path, result)
        write_metadata(metadata_path, metadata)

    try:
        result = apply_logged_curation(result, args.run_dir / "model" / "create-briefs-curation.json")
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"brief curation failed: {exc}", file=sys.stderr)
        return 1
    briefs = result.get("briefs") if isinstance(result, dict) else None
    if not isinstance(briefs, list) or [brief.get("piece_id") for brief in briefs] != ["01", "02", "03"]:
        print("brief creation must return pieces 01, 02, and 03 in order", file=sys.stderr)
        return 1
    if not repair_briefs(
        args.run_dir,
        briefs,
        accepted_keys,
        items_by_key,
        item_payload,
        payload["project"],
        payload["editorial_policy"],
    ):
        return 1
    used_kinds: set[str] = set()
    normalizations = []
    assignment_extensions: dict[tuple[str, str], set[str]] = {}
    for brief in briefs:
        piece_id = brief["piece_id"]
        claims = brief.get("claims")
        if not isinstance(claims, list) or not claims:
            print(f"piece {piece_id} has no claims", file=sys.stderr)
            return 1
        publishers: set[str] = set()
        seen_claim_ids: set[str] = set()
        for claim_number, claim in enumerate(claims, 1):
            desired_id = f"{piece_id}-c{claim_number}"
            if claim.get("claim_id") != desired_id:
                normalizations.append({
                    "piece_id": piece_id,
                    "model_claim_id": claim.get("claim_id"),
                    "stored_claim_id": desired_id,
                })
                claim["claim_id"] = desired_id
            claim_id = claim.get("claim_id", "")
            if not claim_id.startswith(f"{piece_id}-c") or claim_id in seen_claim_ids:
                print(f"piece {piece_id} has invalid or duplicate claim_id: {claim_id}", file=sys.stderr)
                return 1
            seen_claim_ids.add(claim_id)
            evidence = claim.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                print(f"claim {claim_id} has no evidence", file=sys.stderr)
                return 1
            for reference in evidence:
                key = (reference.get("item_id"), reference.get("version_id"))
                if key not in accepted_keys:
                    print(f"claim {claim_id} cites evidence that was not accepted", file=sys.stderr)
                    return 1
                if piece_id not in assignments.get(key, set()):
                    assignment_extensions.setdefault(key, set()).add(piece_id)
                item = items_by_key[key]
                original_quote = align_text_quote(reference, item)
                if original_quote is not None:
                    normalizations.append({
                        "piece_id": piece_id,
                        "claim_id": claim_id,
                        "item_id": item["item_id"],
                        "model_quote": original_quote,
                        "stored_quote": reference["locator"]["quote"],
                    })
                error = resolve_locator(reference, items_by_key)
                if error:
                    print(f"claim {claim_id} has unresolved evidence: {error}", file=sys.stderr)
                    return 1
                publishers.add(item["publisher_id"])
                used_kinds.add(item["kind"])
        if len(publishers) < 3:
            print(f"piece {piece_id} uses only {len(publishers)} independent publishers; three are required", file=sys.stderr)
            return 1
    missing_kinds = {"feed", "youtube", "podcast"} - used_kinds
    if missing_kinds:
        print(f"brief series is missing required media evidence: {', '.join(sorted(missing_kinds))}", file=sys.stderr)
        return 1

    assignment_log = []
    if assignment_extensions:
        for decision in decisions:
            key = (decision.get("item_id"), decision.get("version_id"))
            additions = assignment_extensions.get(key, set())
            if additions:
                before = list(decision["piece_ids"])
                decision["piece_ids"] = sorted(set(before) | additions)
                assignment_log.append({
                    "item_id": key[0], "version_id": key[1],
                    "before": before, "after": decision["piece_ids"],
                    "reason": "The brief cites this already accepted item in an additional piece.",
                })
        decision_path = args.run_dir / "decisions.jsonl"
        if decision_path.is_file():
            temporary = decision_path.with_name(".decisions-with-brief-assignments.jsonl")
            temporary.write_text(
                "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in decisions),
                encoding="utf-8",
            )
            temporary.replace(decision_path)

    with args.output.open("w", encoding="utf-8") as handle:
        for brief in briefs:
            handle.write(json.dumps(brief, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_metadata(args.run_dir / "model" / "create-briefs.json", metadata)
    write_metadata(args.run_dir / "model" / "create-briefs-normalizations.json", normalizations)
    write_metadata(args.run_dir / "model" / "create-briefs-assignment-extensions.json", assignment_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
