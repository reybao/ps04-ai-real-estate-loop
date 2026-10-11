#!/usr/bin/env python3
"""Verify approval and assemble an immutable-by-review production handoff."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from evidence_pack import brief_evidence_details, read_jsonl  # noqa: E402


def fail(message: str) -> int:
    print(f"package preparation failed: {message}", file=sys.stderr)
    return 1


def load_object(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def validate_links(value: object) -> list[dict]:
    if not isinstance(value, list) or [row.get("piece_id") for row in value if isinstance(row, dict)] != ["01", "02", "03"]:
        raise ValueError("publication_links.json must contain pieces 01, 02, and 03")
    for row in value:
        if set(row) != {"piece_id", "substack_url", "youtube_url"}:
            raise ValueError("publication link records require piece_id, substack_url, and youtube_url")
        for key in ("substack_url", "youtube_url"):
            if row[key] is not None and not isinstance(row[key], str):
                raise ValueError(f"{key} must be a string or null")
    return value


def timestamp(seconds: object) -> str:
    value = max(0, int(float(seconds)))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


def source_notes(piece: dict, eligible: list[dict]) -> str:
    lines = [f"# Source Notes — Piece {piece['piece_id']}: {piece['title']}", ""]
    for claim in piece.get("claims", []):
        lines.extend([f"## {claim['claim_id']}", "", claim["statement"], ""])
        for detail in brief_evidence_details({"claims": [claim]}, eligible):
            label = f"{detail['publisher_id']}: {detail['title']}"
            locator = detail["locator"]
            if locator["type"] == "segment":
                segment = detail["segment"]
                location = f"transcript {locator['segment_id']} at {timestamp(segment['start_seconds'])}"
                excerpt = segment["text"]
            else:
                location = "retained article text"
                excerpt = detail["quote"]
            lines.extend([
                f"- [{label}]({detail['url']}) — {location}; published {str(detail['published_at'])[:10]}; "
                f"item `{detail['item_id']}`, version `{detail['version_id']}`.",
                f"  - Evidence: “{excerpt}”",
            ])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 publishing/prepare_package.py RUN_DIR", file=sys.stderr)
        return 2
    run_dir = pathlib.Path(sys.argv[1])
    try:
        saved_review = load_object(run_dir / "review.json")
        approval = load_object(run_dir / "approval.json")
    except FileNotFoundError as exc:
        return fail(f"missing {exc.filename}; complete review and human approval first")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return fail(str(exc))

    current = subprocess.run(
        ["bash", str(ROOT / "review/check_content.sh"), str(run_dir)],
        cwd=ROOT, text=True, capture_output=True,
    )
    if current.returncode != 0:
        return fail(current.stderr.strip() or "current content review could not run")
    try:
        current_review = json.loads(current.stdout)
    except json.JSONDecodeError:
        return fail("current content review returned invalid JSON")
    if not saved_review.get("passed") or not current_review.get("passed"):
        return fail("content checks have blocking errors")
    if saved_review.get("review_id") != current_review.get("review_id"):
        return fail("saved review is stale because reviewed inputs changed")
    if approval.get("review_id") != current_review.get("review_id"):
        return fail("human approval does not match the current review_id")
    if approval.get("decision") != "approve":
        return fail("human approval decision is not 'approve'")
    for field in ("reviewer", "reviewed_at", "notes"):
        if not isinstance(approval.get(field), str) or not approval[field].strip():
            return fail(f"approval.json requires nonempty {field}")

    try:
        briefs = read_jsonl(run_dir / "briefs.jsonl")
        articles = read_jsonl(run_dir / "articles.jsonl")
        scripts = read_jsonl(run_dir / "video_scripts.jsonl")
        eligible = read_jsonl(run_dir / "eligible.jsonl")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return fail(str(exc))
    package = run_dir / "package"
    package.mkdir(parents=True, exist_ok=True)

    canonical_links = run_dir / "publication_links.json"
    packaged_links = package / "publication_links.json"
    try:
        if canonical_links.is_file():
            links = validate_links(json.loads(canonical_links.read_text(encoding="utf-8")))
        elif packaged_links.is_file():
            links = validate_links(json.loads(packaged_links.read_text(encoding="utf-8")))
        else:
            links = [
                {"piece_id": piece_id, "substack_url": None, "youtube_url": None}
                for piece_id in ("01", "02", "03")
            ]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return fail(str(exc))
    link_text = json.dumps(links, indent=2, ensure_ascii=False) + "\n"
    canonical_links.write_text(link_text, encoding="utf-8")
    packaged_links.write_text(link_text, encoding="utf-8")

    article_by_piece = {row["piece_id"]: row for row in articles}
    script_by_piece = {row["piece_id"]: row for row in scripts}
    assets = []
    for brief in briefs:
        piece_id = brief["piece_id"]
        article_source = ROOT / article_by_piece[piece_id]["path"]
        script_source = ROOT / script_by_piece[piece_id]["path"]
        article_target = package / f"article-{piece_id}.md"
        script_target = package / f"video-script-{piece_id}.md"
        notes_target = package / f"source-notes-{piece_id}.md"
        shutil.copy2(article_source, article_target)
        shutil.copy2(script_source, script_target)
        notes_target.write_text(source_notes(brief, eligible), encoding="utf-8")
        assets.append({
            "piece_id": piece_id,
            "article": article_target.name,
            "video_script": script_target.name,
            "source_notes": notes_target.name,
        })

    manifest = {
        "run_id": load_object(run_dir / "run.json").get("run_id"),
        "review_id": current_review["review_id"],
        "approved_by": approval["reviewer"],
        "prepared_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "assets": assets,
        "publication_links": "publication_links.json",
        "manual_steps_remaining": [
            "Render each script in HeyGen or Google Vids using the authorized avatar/voice and listed visuals.",
            "Human-review each rendered video for factual, visual, pronunciation, disclosure, and consent issues.",
            "Publish each article to Substack with free shareable access and its paired video link.",
            "Upload each video to YouTube, add article/source links to the description, and verify access.",
            "Enter the six final URLs in publication_links.json and complete SUBMISSION.md.",
        ],
    }
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    (package / "manifest.json").write_text(manifest_text, encoding="utf-8")
    sys.stdout.write(manifest_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
