#!/usr/bin/env python3
"""Protocol-level RSS/Atom reader shared by the three source collectors."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import email.utils
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import pathlib
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET


USER_AGENT = "MIT-1.125-PS04/1.0 (academic intelligence pipeline)"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(element: ET.Element, name: str) -> ET.Element | None:
    for candidate in element:
        if local_name(candidate.tag) == name:
            return candidate
    return None


def child_text(element: ET.Element, *names: str) -> str | None:
    for name in names:
        candidate = child(element, name)
        if candidate is not None and candidate.text and candidate.text.strip():
            return candidate.text.strip()
    return None


def normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable_digest(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:24]


def atom_link(entry: ET.Element) -> str | None:
    fallback = None
    for candidate in entry:
        if local_name(candidate.tag) != "link":
            continue
        href = candidate.attrib.get("href")
        if not href:
            continue
        fallback = fallback or href
        if candidate.attrib.get("rel", "alternate") == "alternate":
            return href
    return fallback


def entries(root: ET.Element) -> list[ET.Element]:
    return [element for element in root.iter() if local_name(element.tag) in {"item", "entry"}]


def fetch_xml(url: str) -> ET.Element:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    return ET.fromstring(payload)


def make_candidate(source: dict, entry: ET.Element, retrieved_at: str) -> dict | None:
    kind = source["kind"]
    is_atom = local_name(entry.tag) == "entry"
    title = child_text(entry, "title") or "Untitled"
    published_at = normalize_date(child_text(entry, "published", "updated", "pubDate", "date"))
    link = atom_link(entry) if is_atom else child_text(entry, "link")
    guid = child_text(entry, "guid", "id")
    media_url = None
    native_id = None

    if kind == "youtube":
        native_id = child_text(entry, "videoId")
        if not native_id and link:
            match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", link)
            native_id = match.group(1) if match else None
        if native_id:
            link = f"https://www.youtube.com/watch?v={native_id}"
            item_id = f"youtube:{native_id}"
        elif link:
            item_id = f"youtube:{stable_digest(link)}"
        else:
            return None
    elif kind == "podcast":
        enclosure = child(entry, "enclosure")
        if enclosure is not None:
            media_url = enclosure.attrib.get("url")
        transcript = child(entry, "transcript")
        transcript_url = transcript.attrib.get("url") if transcript is not None else None
        transcript_type = transcript.attrib.get("type") if transcript is not None else None
        identity = guid or media_url or link
        if not identity or not link:
            return None
        native_id = guid
        item_id = f"podcast:{stable_digest(identity)}"
    else:
        identity = guid or link
        if not identity or not link:
            return None
        native_id = guid
        item_id = f"feed:{stable_digest(identity)}"

    if not link:
        return None
    candidate = {
        "item_id": item_id,
        "source_id": source["source_id"],
        "publisher_id": source["publisher_id"],
        "kind": kind,
        "title": unescape(title),
        "url": link,
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "media_url": media_url,
        "native_id": native_id,
        "source_feed_url": source["url"],
    }
    if kind == "podcast":
        candidate["transcript_url"] = transcript_url
        candidate["transcript_type"] = transcript_type
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=("feed", "youtube", "podcast"))
    parser.add_argument("--sources", required=True)
    args = parser.parse_args()

    try:
        configured = json.loads(pathlib.Path(args.sources).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"invalid source configuration: {exc}", file=sys.stderr)
        return 2
    if not isinstance(configured, list):
        print("source configuration must contain a JSON array", file=sys.stderr)
        return 2
    selected = [source for source in configured if isinstance(source, dict) and source.get("kind") == args.kind]
    if not selected:
        print(f"no configured {args.kind} sources", file=sys.stderr)
        return 1

    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    failures = 0
    output = []
    seen = set()
    for source in selected:
        try:
            for field in ("source_id", "publisher_id", "url"):
                if not isinstance(source.get(field), str) or not source[field]:
                    raise ValueError(f"missing nonempty {field}")
            root = fetch_xml(source["url"])
            limit = source.get("max_items", 25)
            if not isinstance(limit, int) or limit < 1:
                raise ValueError("max_items must be a positive integer")
            source_count = 0
            for entry in entries(root):
                candidate = make_candidate(source, entry, retrieved_at)
                if candidate is None:
                    continue
                observation_key = (candidate["source_id"], candidate["item_id"])
                if observation_key in seen:
                    continue
                seen.add(observation_key)
                output.append(candidate)
                source_count += 1
                if source_count >= limit:
                    break
            if source_count == 0:
                raise ValueError("feed contained no usable entries")
        except Exception as exc:
            failures += 1
            print(f"{source.get('source_id', 'unknown-source')}: {type(exc).__name__}: {exc}", file=sys.stderr)

    for candidate in output:
        print(json.dumps(candidate, separators=(",", ":"), ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
