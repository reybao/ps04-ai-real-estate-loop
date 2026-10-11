#!/usr/bin/env python3
"""Deterministically assess briefs, drafts, scripts, and evidence references."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from evidence_pack import evidence_index, read_jsonl, resolve_locator  # noqa: E402


def issue(issues: list[dict], artifact: str, severity: str, message: str, piece_id: str | None = None) -> None:
    row = {"artifact": artifact, "severity": severity, "message": message}
    if piece_id is not None:
        row["piece_id"] = piece_id
    issues.append(row)


def words(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z0-9][A-Za-z0-9'’-]*\b", text))


def approximate_content_words(kind: str, text: str) -> int:
    if kind == "article":
        body = re.split(
            r"(?im)^#{1,3}\s+(?:source notes?|sources|references)\b",
            text,
            maxsplit=1,
        )[0]
        return words(body)
    narration_blocks = re.findall(
        r"(?ims)^\s*(?:[-*]\s*)?(?:\*\*)?narration(?:\*\*)?\s*:\s*"
        r"(.*?)(?=^\s*(?:\*\*)?(?:on-screen text|scene direction|visual|narration)"
        r"(?:\*\*)?\s*:|^\s*#{1,6}\s|\Z)",
        text,
    )
    if narration_blocks:
        return words(" ".join(narration_blocks))
    # Fallback when the script uses prose blocks instead of Narration labels.
    filtered = "\n".join(
        line for line in text.splitlines()
        if not re.match(r"(?i)^\s*(#|visual|scene|on-screen|timing|source|description)", line)
    )
    return words(filtered)


def safe_manifest_path(relative: object) -> pathlib.Path | None:
    if not isinstance(relative, str):
        return None
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        return None
    return path


def load_jsonl_checked(path: pathlib.Path, issues: list[dict]) -> list[dict]:
    if not path.is_file():
        issue(issues, path.name, "error", "Required artifact is missing.")
        return []
    try:
        return read_jsonl(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        issue(issues, path.name, "error", f"Artifact is unreadable: {exc}")
        return []


def assess(run_dir: pathlib.Path) -> dict:
    issues: list[dict] = []
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        raise RuntimeError("RUN_DIR must contain run.json")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    as_of = run.get("as_of_date")
    briefs = load_jsonl_checked(run_dir / "briefs.jsonl", issues)
    decisions = load_jsonl_checked(run_dir / "decisions.jsonl", issues)
    article_manifests = load_jsonl_checked(run_dir / "articles.jsonl", issues)
    script_manifests = load_jsonl_checked(run_dir / "video_scripts.jsonl", issues)
    eligible = load_jsonl_checked(run_dir / "eligible.jsonl", issues)
    item_index = evidence_index(eligible) if eligible else {}
    eligible_unique = {row.get("item_id"): row for row in eligible if row.get("item_id")}
    eligible_kinds = Counter(row.get("kind") for row in eligible_unique.values())
    eligible_publishers = {
        row.get("publisher_id") for row in eligible_unique.values() if row.get("publisher_id")
    }
    if len(eligible_unique) < 12:
        issue(issues, "eligible.jsonl", "error", "At least 12 distinct substantive items are required.")
    if len(eligible_publishers) < 6:
        issue(issues, "eligible.jsonl", "error", "At least six independent publishers are required.")
    for kind in ("feed", "youtube", "podcast"):
        if eligible_kinds[kind] < 2:
            issue(
                issues, "eligible.jsonl", "error",
                f"At least two eligible {kind} items are required; found {eligible_kinds[kind]}.",
            )
    assignments = {
        (row.get("item_id"), row.get("version_id")): set(row.get("piece_ids", []))
        for row in decisions if row.get("decision") == "accept"
    }

    expected = ["01", "02", "03"]
    if [row.get("piece_id") for row in briefs] != expected:
        issue(issues, "briefs.jsonl", "error", "Exactly three ordered briefs (01, 02, 03) are required.")
    if [row.get("piece_id") for row in article_manifests] != expected:
        issue(issues, "articles.jsonl", "error", "Exactly three ordered article manifests are required.")
    if [row.get("piece_id") for row in script_manifests] != expected:
        issue(issues, "video_scripts.jsonl", "error", "Exactly three ordered video-script manifests are required.")

    brief_by_piece = {row.get("piece_id"): row for row in briefs if row.get("piece_id") in expected}
    article_by_piece = {row.get("piece_id"): row for row in article_manifests if row.get("piece_id") in expected}
    script_by_piece = {row.get("piece_id"): row for row in script_manifests if row.get("piece_id") in expected}
    assessed_paths = [
        run_path, run_dir / "eligible.jsonl", run_dir / "decisions.jsonl", run_dir / "briefs.jsonl",
        run_dir / "articles.jsonl", run_dir / "video_scripts.jsonl",
    ]
    used_evidence: set[tuple[str, str]] = set()
    used_kinds: set[str] = set()
    titles: list[str] = []

    for piece_id in expected:
        brief = brief_by_piece.get(piece_id)
        if not brief:
            continue
        titles.append(str(brief.get("title", "")).strip().lower())
        claims = brief.get("claims")
        if not isinstance(claims, list) or not claims:
            issue(issues, "briefs.jsonl", "error", "Brief has no claims.", piece_id)
            continue
        claim_ids = [claim.get("claim_id") for claim in claims]
        if len(set(claim_ids)) != len(claim_ids) or any(
            not isinstance(value, str) or not value.startswith(f"{piece_id}-c") for value in claim_ids
        ):
            issue(issues, "briefs.jsonl", "error", "Claim IDs are missing, duplicated, or use the wrong piece prefix.", piece_id)
        publishers: set[str] = set()
        for claim in claims:
            references = claim.get("evidence")
            if not isinstance(references, list) or not references:
                issue(issues, "briefs.jsonl", "error", f"Claim {claim.get('claim_id')} has no evidence.", piece_id)
                continue
            for reference in references:
                error = resolve_locator(reference, item_index)
                if error:
                    issue(
                        issues, "briefs.jsonl", "error",
                        f"Claim {claim.get('claim_id')} has unresolved evidence: {error}.", piece_id,
                    )
                    continue
                key = (reference["item_id"], reference["version_id"])
                item = item_index[key]
                if piece_id not in assignments.get(key, set()):
                    issue(
                        issues, "decisions.jsonl", "error",
                        f"Claim {claim.get('claim_id')} uses evidence not accepted and assigned to this piece.", piece_id,
                    )
                publishers.add(item["publisher_id"])
                used_kinds.add(item["kind"])
                used_evidence.add(key)
                for field in ("text_path", "segments_path"):
                    relative = item.get(field)
                    if relative:
                        assessed_paths.append(ROOT / relative)
        if len(publishers) < 3:
            issue(
                issues, "briefs.jsonl", "error",
                f"Central argument cites {len(publishers)} independent publisher(s); at least three are required.", piece_id,
            )

        for kind, manifest, target_range in (
            ("article", article_by_piece.get(piece_id), (600, 900)),
            ("video script", script_by_piece.get(piece_id), (450, 650)),
        ):
            artifact = "articles.jsonl" if kind == "article" else "video_scripts.jsonl"
            if not manifest:
                continue
            if set(manifest.get("claim_ids", [])) != set(claim_ids):
                issue(issues, artifact, "error", f"{kind.title()} manifest claim IDs differ from the brief.", piece_id)
            path = safe_manifest_path(manifest.get("path"))
            if path is None or not path.is_file():
                issue(issues, artifact, "error", f"{kind.title()} file path is missing or unsafe.", piece_id)
                continue
            assessed_paths.append(path)
            text = path.read_text(encoding="utf-8")
            missing = [value for value in claim_ids if value not in text]
            if missing:
                issue(issues, relative_name(path), "error", f"Missing claim markers: {', '.join(missing)}.", piece_id)
            if kind == "article":
                stated_date = False
                if isinstance(as_of, str):
                    date = datetime.fromisoformat(as_of)
                    human_date = date.strftime("%B %d, %Y").replace(" 0", " ")
                    stated_date = "as of" in text.lower() and any(
                        value in text for value in (as_of, human_date)
                    )
                if not stated_date:
                    issue(issues, relative_name(path), "error", "Article does not state the run as-of date.", piece_id)
            count = approximate_content_words(kind, text)
            low, high = target_range
            if count < low or count > high:
                issue(
                    issues, relative_name(path), "warning",
                    f"Approximate {kind} word count is {count}; target is {low}-{high}.", piece_id,
                )
            if kind == "video script":
                lowered = text.lower()
                legacy_disclosure = "cloned voice" in lowered
                mixed_voice_disclosure = "synthesized author voice" in lowered and "preset voice" in lowered
                if "ai-generated" not in lowered or "avatar" not in lowered or not (legacy_disclosure or mixed_voice_disclosure):
                    issue(issues, relative_name(path), "error", "Required AI avatar/voice disclosure is missing.", piece_id)

    if len(titles) == 3 and len(set(titles)) != 3:
        issue(issues, "briefs.jsonl", "error", "The three pieces do not have distinct titles.")
    missing_kinds = {"feed", "youtube", "podcast"} - used_kinds
    if missing_kinds:
        issue(issues, "briefs.jsonl", "error", f"Series does not use required evidence kind(s): {', '.join(sorted(missing_kinds))}.")
    caption_only = []
    for key in used_evidence:
        item = item_index[key]
        if item.get("kind") != "youtube":
            continue
        raw = item.get("raw_path")
        media_file = ROOT / raw if isinstance(raw, str) and raw else None
        has_media = bool(
            media_file and media_file.is_file()
            and item.get("media_status") in {"video_retained", "audio_retained"}
        )
        if not has_media:
            caption_only.append(key)
    if caption_only:
        issue(
            issues, "youtube-media", "warning",
            f"{len(caption_only)} cited YouTube item(s) have timestamped captions but no retained video/audio file; disclose or repair the media-download gap.",
        )
    issue(
        issues, "human-review", "warning",
        "A human must assess interpretation, factual framing, quotations, visuals, voice/avatar consent, and publication readiness.",
    )

    hasher = hashlib.sha256()
    hasher.update(str(as_of).encode("utf-8"))
    unique_paths = sorted({path.resolve() for path in assessed_paths if path.is_file()}, key=str)
    for path in unique_paths:
        hasher.update(relative_name(path).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    review_id = hasher.hexdigest()
    blocking = any(row["severity"] == "error" for row in issues)
    return {
        "review_id": review_id,
        "passed": not blocking,
        "assessed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "as_of_date": as_of,
        "evidence_item_count": len(used_evidence),
        "issues": issues,
    }


def relative_name(path: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 review/check_content.py RUN_DIR", file=sys.stderr)
        return 2
    try:
        result = assess(pathlib.Path(sys.argv[1]))
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"content assessment could not run: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
