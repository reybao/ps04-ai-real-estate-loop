#!/usr/bin/env python3
"""Generate three article Markdown files from validated briefs."""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from evidence_pack import brief_evidence_details, read_jsonl  # noqa: E402
from openai_request import OpenAIRequestError, request_json, write_metadata  # noqa: E402


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "piece_id": {"type": "string", "enum": ["01", "02", "03"]},
        "title": {"type": "string"},
        "markdown": {"type": "string"},
        "claim_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["piece_id", "title", "markdown", "claim_ids"],
}


def relative(path: pathlib.Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=pathlib.Path)
    parser.add_argument("briefs", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()
    briefs = read_jsonl(args.briefs)
    eligible = read_jsonl(args.run_dir / "eligible.jsonl")
    if [row.get("piece_id") for row in briefs] != ["01", "02", "03"]:
        print("article generation requires exactly briefs 01, 02, and 03", file=sys.stderr)
        return 1
    instructions = (args.run_dir / "prompts/write_articles.md").read_text(encoding="utf-8")
    run = json.loads((args.run_dir / "run.json").read_text(encoding="utf-8"))
    project = json.loads((args.run_dir / "config/project.json").read_text(encoding="utf-8"))
    output_dir = args.run_dir / "articles"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests, metadata_rows = [], []
    for brief in briefs:
        piece_id = brief["piece_id"]
        claim_ids = [claim["claim_id"] for claim in brief["claims"]]
        payload = {
            "as_of_date": run["as_of_date"],
            "project": project,
            "brief": brief,
            "evidence_details": brief_evidence_details(brief, eligible),
            "output_requirements": {
                "language": "English",
                "body_word_target": "600-900 words excluding source notes",
                "citation_style": "Use [claim-id] markers in prose and readable linked source notes.",
            },
        }
        request_path = args.run_dir / "model" / f"write-article-{piece_id}-request.json"
        raw_path = args.run_dir / "model" / f"write-article-{piece_id}-raw.json"
        metadata_path = args.run_dir / "model" / f"write-article-{piece_id}-metadata.json"
        request_record = {
            "instructions": instructions, "input": payload,
            "schema_name": f"ps04_article_{piece_id}", "schema": SCHEMA,
        }
        result = None
        try:
            if request_path.is_file() and raw_path.is_file():
                if json.loads(request_path.read_text(encoding="utf-8")) == request_record:
                    result = json.loads(raw_path.read_text(encoding="utf-8"))
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
                    schema_name=f"ps04_article_{piece_id}",
                    schema=SCHEMA,
                    max_output_tokens=9000,
                )
            except OpenAIRequestError as exc:
                print(f"article {piece_id} generation failed: {exc}", file=sys.stderr)
                return 1
            write_metadata(raw_path, result)
            write_metadata(metadata_path, metadata)
        if not isinstance(result, dict):
            print(f"article {piece_id} returned invalid structured content", file=sys.stderr)
            return 1
        markdown = result.get("markdown")
        if result.get("piece_id") != piece_id or not isinstance(markdown, str) or not markdown.strip():
            print(f"article {piece_id} returned invalid structured content", file=sys.stderr)
            return 1
        if not markdown.lstrip().startswith("# "):
            markdown = f"# {result['title'].strip()}\n\n{markdown.lstrip()}"
        if set(result.get("claim_ids", [])) != set(claim_ids):
            print(f"article {piece_id} did not preserve the brief's claim IDs", file=sys.stderr)
            return 1
        missing = [claim_id for claim_id in claim_ids if claim_id not in markdown]
        if missing:
            print(f"article {piece_id} omits claim markers: {', '.join(missing)}", file=sys.stderr)
            return 1
        as_of = datetime.date.fromisoformat(run["as_of_date"])
        human_date = as_of.strftime("%B %d, %Y").replace(" 0", " ")
        if "as of" not in markdown.lower() or not any(
            date in markdown for date in (run["as_of_date"], human_date)
        ):
            print(f"article {piece_id} omits the run as-of date", file=sys.stderr)
            return 1
        path = output_dir / f"{piece_id}.md"
        path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        manifests.append({"piece_id": piece_id, "path": relative(path), "claim_ids": claim_ids})
        metadata_rows.append({"piece_id": piece_id, **metadata})
    with args.output.open("w", encoding="utf-8") as handle:
        for row in manifests:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_metadata(args.run_dir / "model" / "write-articles.json", metadata_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
