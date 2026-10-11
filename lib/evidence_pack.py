#!/usr/bin/env python3
"""Build bounded, traceable evidence excerpts for model-facing stages."""

from __future__ import annotations

import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
KEYWORDS = re.compile(
    r"\b(ai|artificial intelligence|data cent(?:er|re)|real estate|property|power|grid|utility|"
    r"energy|land|zoning|permit|construction|capital|finance|investment|water|community|"
    r"hyperscale|compute|infrastructure|lease|vacancy|demand)\b",
    re.I,
)
MEDIA_TERMS = (
    (re.compile(r"\b(grid|interconnect|power|electric|utility|substation)\b", re.I), 4),
    (re.compile(r"\b(land|zoning|permit|entitlement|site|construction|delivery)\b", re.I), 4),
    (re.compile(r"\b(lease|tenant|capital|financ|invest|cost|rate|water|community)\b", re.I), 3),
    (re.compile(r"\b(real estate|property|data center|AI)\b", re.I), 1),
)


def read_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}: line {number} is not an object")
        rows.append(value)
    return rows


def _ranked_indexes(values: list[str], limit: int) -> list[int]:
    chosen: list[int] = []
    for index in range(min(3, len(values))):
        chosen.append(index)
    for index, value in enumerate(values):
        if KEYWORDS.search(value) and index not in chosen:
            chosen.append(index)
            if len(chosen) >= limit:
                break
    if len(chosen) < limit and values:
        step = max(1, len(values) // max(1, limit - len(chosen)))
        for index in range(0, len(values), step):
            if index not in chosen:
                chosen.append(index)
                if len(chosen) >= limit:
                    break
    return sorted(chosen)


def _media_window_indexes(segments: list[dict], limit: int) -> list[int]:
    """Pick coherent windows spread across an entire recording."""
    if len(segments) <= limit:
        return list(range(len(segments)))
    window_count = min(8, max(1, limit // 8))
    window_size = max(1, limit // window_count)
    chosen: set[int] = set()
    for bucket in range(window_count):
        low = len(segments) * bucket // window_count
        high = len(segments) * (bucket + 1) // window_count
        latest_start = max(low, high - window_size)
        best_start = low
        best_score = -1
        for start in range(low, latest_start + 1):
            window = segments[start:start + window_size]
            score = sum(
                weight * bool(pattern.search(str(segment.get("text", ""))))
                for segment in window for pattern, weight in MEDIA_TERMS
            )
            if score > best_score:
                best_start, best_score = start, score
        chosen.update(range(best_start, min(best_start + window_size, len(segments))))
    return sorted(chosen)[:limit]


def item_excerpt(item: dict, *, text_limit: int = 7000, segment_limit: int = 80) -> dict:
    record = {
        key: item.get(key)
        for key in (
            "item_id", "version_id", "source_id", "publisher_id", "kind", "title", "url",
            "published_at",
        )
    }
    segments_path = item.get("segments_path")
    if segments_path:
        segments = json.loads((ROOT / segments_path).read_text(encoding="utf-8"))
        record["evidence_segments"] = [
            segments[index] for index in _media_window_indexes(segments, segment_limit)
        ]
        record["excerpt_note"] = (
            "Coherent transcript windows sampled across the full recording; "
            "segment IDs and timestamps remain resolvable."
        )
        return record

    text_path = item.get("text_path")
    if not text_path:
        record["evidence_paragraphs"] = []
        return record
    text = (ROOT / text_path).read_text(encoding="utf-8")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    selected = []
    used = 0
    for index in _ranked_indexes(paragraphs, 16):
        paragraph = paragraphs[index]
        if selected and used + len(paragraph) > text_limit:
            continue
        selected.append(paragraph)
        used += len(paragraph)
    record["evidence_paragraphs"] = selected
    record["excerpt_note"] = "Bounded exact paragraphs; quotes must match retained text."
    return record


def evidence_index(items: list[dict]) -> dict[tuple[str, str], dict]:
    return {(item["item_id"], item["version_id"]): item for item in items}


def resolve_locator(reference: dict, items_by_version: dict[tuple[str, str], dict]) -> str | None:
    key = (reference.get("item_id"), reference.get("version_id"))
    item = items_by_version.get(key)
    if item is None:
        return "item/version does not exist in eligible evidence"
    locator = reference.get("locator")
    if not isinstance(locator, dict):
        return "locator is not an object"
    if locator.get("type") == "text":
        quote = locator.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            return "text locator has no quote"
        text_path = item.get("text_path")
        if not text_path or quote not in (ROOT / text_path).read_text(encoding="utf-8"):
            return "quote does not occur exactly in retained text"
        return None
    if locator.get("type") == "segment":
        segment_id = locator.get("segment_id")
        path = item.get("segments_path")
        if not path:
            return "segment locator points to item without segments"
        segments = json.loads((ROOT / path).read_text(encoding="utf-8"))
        if not any(segment.get("segment_id") == segment_id for segment in segments):
            return "segment_id does not exist in retained transcript"
        return None
    return "locator type must be text or segment"


def reference_detail(reference: dict, items_by_version: dict[tuple[str, str], dict]) -> dict:
    """Return audience-facing source metadata for one already-validated reference."""
    item = items_by_version[(reference["item_id"], reference["version_id"])]
    locator = reference["locator"]
    detail = {
        "item_id": item["item_id"],
        "version_id": item["version_id"],
        "title": item["title"],
        "publisher_id": item["publisher_id"],
        "kind": item["kind"],
        "published_at": item["published_at"],
        "url": item["url"],
        "locator": locator,
    }
    if locator["type"] == "segment":
        segments = json.loads((ROOT / item["segments_path"]).read_text(encoding="utf-8"))
        segment = next(row for row in segments if row.get("segment_id") == locator["segment_id"])
        detail["segment"] = segment
    else:
        detail["quote"] = locator["quote"]
    return detail


def brief_evidence_details(brief: dict, items: list[dict]) -> list[dict]:
    index = evidence_index(items)
    seen: set[tuple[str, str, str]] = set()
    details = []
    for claim in brief.get("claims", []):
        for reference in claim.get("evidence", []):
            locator = reference.get("locator", {})
            locator_value = locator.get("quote") or locator.get("segment_id") or ""
            key = (reference.get("item_id", ""), reference.get("version_id", ""), locator_value)
            if key in seen:
                continue
            seen.add(key)
            details.append(reference_detail(reference, index))
    return details
