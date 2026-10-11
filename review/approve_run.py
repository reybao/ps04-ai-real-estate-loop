#!/usr/bin/env python3
"""Record an explicit terminal review decision before packaging a run."""

from __future__ import annotations

from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def current_review(run_dir: Path) -> dict:
    saved = load_object(run_dir / "review.json")
    result = subprocess.run(
        ["bash", str(ROOT / "review/check_content.sh"), str(run_dir)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "content review could not run")
    fresh = json.loads(result.stdout)
    if not saved.get("passed") or not fresh.get("passed"):
        raise ValueError("content checks have blocking errors; correct them before approval")
    if not fresh.get("review_id") or saved.get("review_id") != fresh.get("review_id"):
        raise ValueError("saved review is stale; rerun review/check_content.sh before approval")
    return fresh


def reviewer_name(approval_path: Path) -> str:
    configured = os.environ.get("PS04_REVIEWER", "").strip()
    if configured:
        return configured
    try:
        previous = load_object(approval_path).get("reviewer", "")
    except (OSError, ValueError, json.JSONDecodeError):
        previous = ""
    if isinstance(previous, str) and previous.strip() and "YOUR" not in previous.upper():
        return previous.strip()
    return getpass.getuser()


def approval_record(
    review_id: str, reviewer: str, decision: str, reviewed_at: str,
    previous: dict | None = None, piece_reviews: list[dict] | None = None,
) -> dict:
    if decision == "approve":
        notes = (
            "Human reviewer confirmed the three articles and paired video scripts for "
            "production handoff; see SUBMISSION.md for detailed editorial judgments and limitations."
        )
        if previous and previous.get("review_id") == review_id and previous.get("decision") == "approve":
            prior_notes = previous.get("notes")
            if isinstance(prior_notes, str) and prior_notes.strip():
                notes = prior_notes.strip()
    else:
        rejected = next((row for row in piece_reviews or [] if row["decision"] == "revise"), None)
        notes = (
            f"Human reviewer requested revisions to piece {rejected['piece_id']}; "
            "this run is not approved for production handoff."
            if rejected else
            "Human reviewer requested revisions; this run is not approved for production handoff."
        )
        if rejected and rejected.get("reason"):
            notes += f" Reason: {rejected['reason']}"
    record = {
        "review_id": review_id,
        "decision": decision,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "notes": notes,
    }
    if piece_reviews is not None:
        record["piece_reviews"] = piece_reviews
    return record


def show_piece(run_dir: Path, piece_id: str) -> None:
    editor = shutil.which("code")
    if not editor:
        raise RuntimeError(
            "VS Code 'code' command was not found; install its Shell Command in VS Code before approval"
        )
    article = run_dir / "articles" / f"{piece_id}.md"
    script = run_dir / "video_scripts" / f"{piece_id}.md"
    # Open the script first so the article is the active tab when the editor appears.
    for path in (script, article):
        result = subprocess.run(
            [editor, "--reuse-window", str(path)], cwd=ROOT,
            text=True, capture_output=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"VS Code could not open {path}")
    print(f"\nOpened piece {piece_id} in VS Code:")
    print(f"  Article: {article}")
    print(f"  Video script: {script}")
    print("Read both tabs, then return to this terminal to record your decision.", flush=True)


def write_approval(path: Path, record: dict) -> Path | None:
    backup = None
    if path.exists():
        history = path.parent / "approval_history"
        history.mkdir(exist_ok=True)
        stamp = now_utc().replace("-", "").replace(":", "")
        backup = history / f"approval-{stamp}-{uuid4().hex[:8]}.json"
        shutil.copy2(path, backup)
    descriptor, temporary = tempfile.mkstemp(prefix=".approval-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 review/approve_run.py RUN_DIR", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("error: approval requires an interactive terminal", file=sys.stderr)
        return 2
    run_dir = Path(sys.argv[1]).resolve()
    try:
        review = current_review(run_dir)
        for folder in ("articles", "video_scripts"):
            for piece_id in ("01", "02", "03"):
                if not (run_dir / folder / f"{piece_id}.md").is_file():
                    raise ValueError(f"missing {folder}/{piece_id}.md")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    approval_path = run_dir / "approval.json"
    reviewer = reviewer_name(approval_path)
    print(f"\nRun: {run_dir.name}")
    print(f"Automated content check: passed (review_id: {review['review_id']})")
    for issue in review.get("issues", []):
        print(f"{issue.get('severity', 'note').title()}: {issue.get('message', '')}")
    print(f"Reviewer recorded as: {reviewer}")
    print("Each article and its paired video script will open in VS Code in turn.")
    print("Check claims, source links, and script consistency before answering.")
    piece_reviews = []
    decision = "approve"
    for piece_id in ("01", "02", "03"):
        try:
            show_piece(run_dir, piece_id)
        except (OSError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"\nDecision for piece {piece_id}:")
        print("1) No adjustment needed; APPROVE this article and its video script.")
        print("2) Adjustment needed; stop before packaging.")
        print("0) Cancel without changing the existing approval.")
        try:
            choice = input("Choose 1, 2, or 0: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCanceled; existing approval unchanged.")
            return 4
        if choice not in {"1", "2"}:
            print("Canceled; existing approval unchanged.")
            return 4
        piece_decision = "approve" if choice == "1" else "revise"
        piece_review = {
            "piece_id": piece_id,
            "decision": piece_decision,
            "reviewed_at": now_utc(),
        }
        if piece_decision == "revise":
            try:
                reason = input("What should change? (brief note; optional for manual edits): ").strip()
                api_choice = input("Generate a separate API revision proposal? [y/N]: ").strip().lower()
                if api_choice in {"y", "yes"}:
                    while not reason:
                        reason = input("Describe the requested change for the API: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCanceled; existing approval unchanged.")
                return 4
            if reason:
                piece_review["reason"] = reason
            piece_review["revision_mode"] = "api" if api_choice in {"y", "yes"} else "manual"
        piece_reviews.append(piece_review)
        if piece_decision == "revise":
            decision = "revise"
            break

    try:
        latest = current_review(run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: content changed during review: {exc}", file=sys.stderr)
        return 1
    if latest["review_id"] != review["review_id"]:
        print("error: content changed during review; no approval was recorded", file=sys.stderr)
        return 1
    try:
        previous = load_object(approval_path)
    except (OSError, ValueError, json.JSONDecodeError):
        previous = None
    record = approval_record(review["review_id"], reviewer, decision, now_utc(), previous, piece_reviews)
    try:
        backup = write_approval(approval_path, record)
    except OSError as exc:
        print(f"error: could not save approval: {exc}", file=sys.stderr)
        return 1
    if backup:
        print(f"Previous approval preserved at: {backup}")
    print(f"Recorded {decision} in {approval_path}")
    if decision == "revise":
        print("Stopped before packaging. Update the drafts and rerun the review.")
        return 3
    print("Proceeding to the package step...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
