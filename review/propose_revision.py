#!/usr/bin/env python3
"""Generate an isolated API revision proposal for a human-requested change."""

from __future__ import annotations

import difflib
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "review"))
from approve_run import current_review, load_object  # noqa: E402
from evidence_pack import brief_evidence_details, read_jsonl  # noqa: E402
from openai_request import OpenAIRequestError, request_json, write_metadata  # noqa: E402


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "piece_id": {"type": "string", "enum": ["01", "02", "03"]},
        "can_revise": {"type": "boolean"},
        "rationale": {"type": "string"},
        "article_markdown": {"type": "string"},
        "video_script_markdown": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "piece_id", "can_revise", "rationale", "article_markdown",
        "video_script_markdown", "changes", "limitations",
    ],
}


def revision_request(run_dir: Path) -> tuple[str, dict, dict] | None:
    approval = load_object(run_dir / "approval.json")
    if approval.get("decision") != "revise":
        raise ValueError("the human approval decision must be revise")
    piece_reviews = approval.get("piece_reviews")
    if not isinstance(piece_reviews, list):
        raise ValueError("approval.json has no per-piece review decisions")
    rejected = next(
        (row for row in piece_reviews if isinstance(row, dict) and row.get("decision") == "revise"),
        None,
    )
    if not rejected or rejected.get("piece_id") not in {"01", "02", "03"}:
        raise ValueError("approval.json has no valid piece to revise")
    if rejected.get("revision_mode") != "api":
        return None
    reason = rejected.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("an API revision requires a specific human change request")
    review = current_review(run_dir)
    if approval.get("review_id") != review.get("review_id"):
        raise ValueError("approval and current review no longer match; review the changed draft again")

    piece_id = rejected["piece_id"]
    briefs = read_jsonl(run_dir / "briefs.jsonl")
    brief = next((row for row in briefs if row.get("piece_id") == piece_id), None)
    if not brief:
        raise ValueError(f"brief for piece {piece_id} is missing")
    eligible = read_jsonl(run_dir / "eligible.jsonl")
    article = (run_dir / "articles" / f"{piece_id}.md").read_text(encoding="utf-8")
    script = (run_dir / "video_scripts" / f"{piece_id}.md").read_text(encoding="utf-8")
    run = load_object(run_dir / "run.json")
    prompt = (ROOT / "prompts/revise_piece.md").read_text(encoding="utf-8")
    payload = {
        "piece_id": piece_id,
        "as_of_date": run.get("as_of_date"),
        "human_request": reason.strip(),
        "brief": brief,
        "evidence_details": brief_evidence_details(brief, eligible),
        "current_article_markdown": article,
        "current_video_script_markdown": script,
    }
    request = {
        "instructions": prompt,
        "input": payload,
        "schema_name": f"ps04_revision_{piece_id}",
        "schema": SCHEMA,
    }
    return piece_id, request, {"article": article, "script": script, "brief": brief}


def validate_proposal(result: object, piece_id: str, original: dict, as_of_date: str) -> bool:
    if not isinstance(result, dict) or result.get("piece_id") != piece_id:
        raise ValueError("API revision returned the wrong piece or an invalid object")
    if not isinstance(result.get("can_revise"), bool):
        raise ValueError("API revision omitted can_revise")
    for field in ("rationale", "article_markdown", "video_script_markdown"):
        if not isinstance(result.get(field), str):
            raise ValueError(f"API revision omitted {field}")
    for field in ("changes", "limitations"):
        if not isinstance(result.get(field), list) or any(not isinstance(x, str) for x in result[field]):
            raise ValueError(f"API revision returned invalid {field}")
    if not result["can_revise"]:
        return False
    article = result["article_markdown"]
    script = result["video_script_markdown"]
    if not article.lstrip().startswith("# ") or not script.lstrip().startswith("# "):
        raise ValueError("proposed article and script must start with Markdown titles")
    claim_ids = [claim["claim_id"] for claim in original["brief"]["claims"]]
    for label, markdown in (("article", article), ("video script", script)):
        missing = [claim_id for claim_id in claim_ids if claim_id not in markdown]
        if missing:
            raise ValueError(f"proposed {label} omits required claim markers: {', '.join(missing)}")
    human_date = date.fromisoformat(as_of_date).strftime("%B %d, %Y").replace(" 0", " ")
    if "as of" not in article.lower() or not any(
        stamp in article for stamp in (as_of_date, human_date)
    ):
        raise ValueError("proposed article omits the run's actual as-of date")
    lowered = script.lower()
    if "ai-generated" not in lowered or "cloned voice" not in lowered:
        raise ValueError("proposed script omits the required avatar/voice disclosure")
    return True


def unified_diff(before: str, after: str, before_name: str, after_name: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=before_name, tofile=after_name,
    ))


def open_proposals_in_vscode(run_dir: Path, piece_id: str, proposal_dir: Path, original: dict, result: dict) -> None:
    editor = shutil.which("code")
    if not editor:
        return
    pairs = [
        (run_dir / "video_scripts" / f"{piece_id}.md", proposal_dir / "video-script-proposed.md", "script"),
        (run_dir / "articles" / f"{piece_id}.md", proposal_dir / "article-proposed.md", "article"),
    ]
    for current, proposed, key in pairs:
        if result[f"{'video_script' if key == 'script' else 'article'}_markdown"].rstrip() == original[key].rstrip():
            continue
        completed = subprocess.run(
            [editor, "--reuse-window", "--diff", str(current), str(proposed)],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        if completed.returncode != 0:
            print(f"warning: could not open VS Code diff for {key}: {completed.stderr.strip()}", file=sys.stderr)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 review/propose_revision.py RUN_DIR", file=sys.stderr)
        return 2
    run_dir = Path(sys.argv[1]).resolve()
    try:
        context = revision_request(run_dir)
        if context is None:
            print("Manual revision selected; no API request was made.")
            return 0
        piece_id, request, original = context
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        proposal_dir = run_dir / "revisions" / piece_id / digest
        request_path = proposal_dir / "request.json"
        response_path = proposal_dir / "response.json"
        metadata_path = proposal_dir / "metadata.json"
        result = None
        if request_path.is_file() and response_path.is_file():
            if load_object(request_path) == request:
                result = load_object(response_path)
                print("Reusing the existing proposal for the same draft and request; no new API call.")
        if result is None:
            write_metadata(request_path, request)
            print(f"Requesting an API revision proposal for piece {piece_id}...", flush=True)
            result, metadata = request_json(
                instructions=request["instructions"],
                input_payload=request["input"],
                schema_name=request["schema_name"],
                schema=SCHEMA,
                max_output_tokens=12000,
            )
            write_metadata(metadata_path, metadata)
            try:
                safe = validate_proposal(result, piece_id, original, str(request["input"]["as_of_date"]))
            except ValueError:
                write_metadata(proposal_dir / "response-invalid.json", result)
                raise
            write_metadata(response_path, result)
        else:
            safe = validate_proposal(result, piece_id, original, str(request["input"]["as_of_date"]))
        feedback = [
            f"# Revision proposal — Piece {piece_id}", "",
            f"Human request: {request['input']['human_request']}", "",
            f"Can revise with current evidence: {'yes' if safe else 'no'}", "",
            f"Model rationale: {result['rationale']}", "",
            "## Proposed changes", "",
        ]
        feedback.extend(f"- {change}" for change in result["changes"])
        feedback.extend(["", "## Remaining limitations", ""])
        feedback.extend(f"- {limitation}" for limitation in result["limitations"])
        feedback.extend(["", "This is a proposal only. The reviewed article and script were not changed.", ""])
        (proposal_dir / "feedback.md").write_text("\n".join(feedback), encoding="utf-8")
        if not safe:
            print(f"The API could not support this change with current evidence. See {proposal_dir / 'feedback.md'}")
            return 0

        article = result["article_markdown"].rstrip() + "\n"
        script = result["video_script_markdown"].rstrip() + "\n"
        (proposal_dir / "article-proposed.md").write_text(article, encoding="utf-8")
        (proposal_dir / "video-script-proposed.md").write_text(script, encoding="utf-8")
        (proposal_dir / "article.diff").write_text(
            unified_diff(original["article"], article, "current-article.md", "article-proposed.md"),
            encoding="utf-8",
        )
        (proposal_dir / "video-script.diff").write_text(
            unified_diff(original["script"], script, "current-video-script.md", "video-script-proposed.md"),
            encoding="utf-8",
        )
        print(f"Proposal saved to {proposal_dir}")
        print("The original article and script are unchanged. Review the differences before applying anything.")
        open_proposals_in_vscode(run_dir, piece_id, proposal_dir, original, result)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, OpenAIRequestError) as exc:
        print(f"revision proposal failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
