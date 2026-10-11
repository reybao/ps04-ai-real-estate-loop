#!/usr/bin/env python3
"""Extract retained article text and timestamped media transcripts."""

from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))
from openai_request import OpenAIRequestError, configuration  # noqa: E402


USER_AGENT = "MIT-1.125-PS04/1.0 (academic intelligence pipeline)"
ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "store.sh"
ASSETS = ROOT / "data" / "assets"
MEDIA = ROOT / "data" / "media"
USED_TOOLS = {"python3"}


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.article_depth = 0
        self.current: list[str] | None = None
        self.current_in_article = False
        self.article_paragraphs: list[str] = []
        self.all_paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "header", "form", "noscript", "svg"}:
            self.skip_depth += 1
        if tag == "article":
            self.article_depth += 1
        if tag in {"p", "h1", "h2", "h3", "li", "blockquote"} and self.skip_depth == 0:
            self.current = []
            self.current_in_article = self.article_depth > 0

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"p", "h1", "h2", "h3", "li", "blockquote"} and self.current is not None:
            text = re.sub(r"\s+", " ", " ".join(self.current)).strip()
            if len(text) >= 25:
                self.all_paragraphs.append(text)
                if self.current_in_article:
                    self.article_paragraphs.append(text)
            self.current = None
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
        if tag in {"script", "style", "nav", "footer", "header", "form", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.skip_depth == 0:
            self.current.append(data)

    def text(self) -> str:
        selected = self.article_paragraphs if sum(map(len, self.article_paragraphs)) >= 500 else self.all_paragraphs
        unique = []
        seen = set()
        for paragraph in selected:
            if paragraph not in seen:
                unique.append(paragraph)
                seen.add(paragraph)
        return "\n\n".join(unique).strip()


def fetch(url: str) -> tuple[bytes, str | None, str | None]:
    USED_TOOLS.add("urllib")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(), response.headers.get("ETag"), response.headers.get("Last-Modified")


def safe_id(item_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", item_id)


def relative(path: pathlib.Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def write_immutable(base: pathlib.Path, item_id: str, digest: str, suffix: str, payload: bytes) -> pathlib.Path:
    directory = base / safe_id(item_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(payload)
    return path


def write_immutable_file(base: pathlib.Path, item_id: str, digest: str, suffix: str, source: pathlib.Path) -> pathlib.Path:
    directory = base / safe_id(item_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}{suffix}"
    if not path.exists():
        shutil.copy2(source, path)
    return path


def download_to_file(url: str, destination: pathlib.Path) -> tuple[str | None, str | None]:
    USED_TOOLS.add("urllib")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)
        return response.headers.get("ETag"), response.headers.get("Last-Modified")


def file_digest(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def time_seconds(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_timed_text(payload: str) -> list[dict]:
    payload = payload.replace("\r\n", "\n").replace("\r", "\n")
    pattern = re.compile(
        r"(?m)^(?:(?:\d+|[^\n]+)\n)?"
        r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->\s*"
        r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})[^\n]*\n"
        r"(?P<text>.*?)(?=\n{2,}|\Z)",
        re.S,
    )
    segments = []
    previous_text = None
    for match in pattern.finditer(payload):
        raw_text = match.group("text")
        start_seconds = time_seconds(match.group("start"))
        end_seconds = time_seconds(match.group("end"))

        # YouTube auto-captions use a rolling two-line VTT format: the first
        # line repeats the preceding cue and the second line contains the new
        # words with inline timestamps.  The 0.01-second bridge cues are also
        # repetitions.  Retaining all of that text triples the transcript.
        rolling_caption = bool(re.search(r"<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}>", raw_text))
        if rolling_caption:
            if end_seconds - start_seconds <= 0.05:
                continue
            tagged_lines = [line for line in raw_text.splitlines() if re.search(r"<c>|<\d", line)]
            if tagged_lines:
                raw_text = tagged_lines[-1]

        text = re.sub(r"<[^>]+>", "", raw_text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or text == previous_text:
            continue
        segments.append({
            "segment_id": f"s{len(segments) + 1:05d}",
            "start_seconds": round(start_seconds, 3),
            "end_seconds": round(end_seconds, 3),
            "text": text,
        })
        previous_text = text
    return segments


def reuse_media(candidate: dict) -> dict | None:
    result = subprocess.run(
        ["bash", str(STORE), "get", candidate["item_id"]],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        stored = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    comparable = ("title", "url", "published_at", "media_url")
    if any(stored.get(key) != candidate.get(key) for key in comparable):
        return None
    paths = [stored.get("text_path"), stored.get("segments_path")]
    if not all(path and (ROOT / path).is_file() for path in paths):
        return None
    if candidate["kind"] == "youtube":
        # A legacy subtitle-only record is not a complete local-media capture.
        # Reprocess it once; future runs can reuse retained video/audio and transcript.
        if stored.get("transcription_method") != "local-openai-whisper":
            return None
        if stored.get("media_status") not in {"video_retained", "audio_retained"}:
            return None
        if stored.get("transcription_model") != os.environ.get("PS04_WHISPER_MODEL", "small.en"):
            return None
        paths = [stored.get("raw_path"), stored.get("transcript_raw_path")]
        if not all(path and (ROOT / path).is_file() for path in paths):
            return None
    reused = dict(stored)
    reused["retrieved_at"] = candidate["retrieved_at"]
    return reused


def article_item(candidate: dict) -> dict:
    payload, etag, last_modified = fetch(candidate["url"])
    raw_digest = hashlib.sha256(payload).hexdigest()
    raw_path = write_immutable(MEDIA, candidate["item_id"], raw_digest, ".html", payload)
    parser = ArticleParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    text = parser.text()
    if len(text) < 300:
        raise ValueError("extracted article text is shorter than 300 characters")
    text_payload = (text + "\n").encode("utf-8")
    text_digest = hashlib.sha256(text_payload).hexdigest()
    text_path = write_immutable(ASSETS, candidate["item_id"], text_digest, ".txt", text_payload)
    item = dict(candidate)
    item.update({
        "text_path": relative(text_path),
        "segments_path": None,
        "raw_path": relative(raw_path),
        "http_etag": etag,
        "http_last_modified": last_modified,
    })
    item["version_id"] = compute_version(item, text, None)
    return item


def local_whisper_paths() -> tuple[pathlib.Path, str, pathlib.Path]:
    cli = pathlib.Path(os.environ.get(
        "PS04_WHISPER_CLI", ROOT / "tmp" / "whisper-venv" / "bin" / "whisper"
    )).expanduser()
    model_name = os.environ.get("PS04_WHISPER_MODEL", "small.en")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", model_name):
        raise RuntimeError("PS04_WHISPER_MODEL must be a local model name, such as small.en")
    model = ROOT / "data" / "models" / f"{model_name}.pt"
    if not cli.is_file():
        raise RuntimeError(f"local Python Whisper command not found: {cli}; see RUN_GUIDE.md")
    if not model.is_file():
        raise RuntimeError(f"local Whisper model not found: {model}; see RUN_GUIDE.md")
    return cli, model_name, model


def youtube_captions(candidate: dict, download_error: str) -> tuple[str, list[dict], pathlib.Path, dict]:
    """Retain platform captions when YouTube blocks the media download."""
    with tempfile.TemporaryDirectory(prefix="ps04-youtube-captions-") as temporary:
        template = str(pathlib.Path(temporary) / "%(id)s.%(ext)s")
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "--skip-download", "--write-subs", "--write-auto-subs",
             "--sub-langs", "en.*,en", "--sub-format", "vtt", "-o", template, candidate["url"]],
            cwd=ROOT, text=True, capture_output=True,
        )
        files = sorted(pathlib.Path(temporary).glob("*.vtt"))
        if not files:
            diagnostic = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no subtitle file"]
            raise RuntimeError(f"YouTube media download failed ({download_error}); captions unavailable: {diagnostic[0]}")
        payload = files[0].read_bytes()
    raw_path = write_immutable(
        MEDIA, candidate["item_id"], hashlib.sha256(payload).hexdigest(), ".vtt", payload
    )
    segments = parse_timed_text(payload.decode("utf-8", errors="replace"))
    if not segments:
        raise ValueError("YouTube subtitle file contained no usable timed segments")
    text = " ".join(segment["text"] for segment in segments)
    return text, segments, raw_path, {
        "transcription_method": "youtube-captions",
        "media_status": "transcript_only",
        "media_download_error": download_error,
    }


def youtube_transcript(candidate: dict) -> tuple[str, list[dict], pathlib.Path, dict]:
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is required to download YouTube video")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for local YouTube transcription")
    USED_TOOLS.update({"yt-dlp", "ffmpeg"})
    with tempfile.TemporaryDirectory(prefix="ps04-youtube-") as temporary:
        temp = pathlib.Path(temporary)
        template = str(temp / "%(id)s.%(ext)s")
        command = [
            "yt-dlp", "--no-playlist", "--no-progress", "--socket-timeout", "30", "--retries", "2",
            "-f", "bv[height<=360]+ba/b[height<=360]/best",
            "--merge-output-format", "mp4", "-o", template, candidate["url"],
        ]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        videos = [path for path in temp.iterdir() if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
        if result.returncode == 0 and len(videos) == 1:
            source_media = videos[0]
            media_status = "video_retained"
            download_method = "default-video"
        else:
            video_error = ((result.stderr or result.stdout).strip().splitlines()[-1:] or ["no video file"])[0]
            alternate_dir = temp / "android-vr-download"
            alternate_dir.mkdir()
            alternate_result = subprocess.run(
                ["yt-dlp", "--no-playlist", "--no-progress", "--socket-timeout", "30", "--retries", "2",
                 "--extractor-args", "youtube:player_client=android_vr", "-f", "18",
                 "-o", str(alternate_dir / "%(id)s.%(ext)s"), candidate["url"]],
                cwd=ROOT, text=True, capture_output=True,
            )
            alternate_videos = [path for path in alternate_dir.iterdir() if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
            if alternate_result.returncode == 0 and len(alternate_videos) == 1:
                source_media = alternate_videos[0]
                media_status = "video_retained"
                download_method = "android_vr-format-18"
            else:
                alternate_error = ((alternate_result.stderr or alternate_result.stdout).strip().splitlines()[-1:] or ["no alternate video file"])[0]
                audio_dir = temp / "audio-download"
                audio_dir.mkdir()
                audio_result = subprocess.run(
                    ["yt-dlp", "--no-playlist", "--no-progress", "--socket-timeout", "30", "--retries", "2",
                     "-f", "ba", "-o", str(audio_dir / "%(id)s.%(ext)s"), candidate["url"]],
                    cwd=ROOT, text=True, capture_output=True,
                )
                audios = [path for path in audio_dir.iterdir() if path.suffix.lower() in {".mp3", ".m4a", ".aac", ".opus", ".webm", ".mp4"}]
                if audio_result.returncode != 0 or len(audios) != 1:
                    audio_error = ((audio_result.stderr or audio_result.stdout).strip().splitlines()[-1:] or ["no audio file"])[0]
                    return youtube_captions(candidate, f"video: {video_error}; alternate video: {alternate_error}; audio: {audio_error}")
                source_media = audios[0]
                media_status = "audio_retained"
                download_method = "audio-only"
        raw_path = write_immutable_file(
            MEDIA, candidate["item_id"], file_digest(source_media), source_media.suffix.lower(), source_media
        )
        cli, model_name, model = local_whisper_paths()
        USED_TOOLS.add("local:openai-whisper")
        wav = temp / "audio.wav"
        conversion = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw_path),
             "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
            cwd=ROOT, text=True, capture_output=True,
        )
        if conversion.returncode != 0 or not wav.is_file():
            raise RuntimeError(f"ffmpeg audio conversion failed: {conversion.stderr.strip()[-500:]}")
        transcription = subprocess.run(
            [str(cli), str(wav), "--model", model_name, "--model_dir", str(model.parent),
             "--device", "cpu", "--language", "en", "--fp16", "False",
             "--output_format", "json", "--output_dir", str(temp), "--verbose", "False"],
            cwd=ROOT, text=True, capture_output=True,
        )
        transcript_file = temp / "audio.json"
        if transcription.returncode != 0 or not transcript_file.is_file():
            diagnostic = (transcription.stderr or transcription.stdout).strip()[-500:]
            raise RuntimeError(f"local Whisper transcription failed: {diagnostic}")
        payload = transcript_file.read_bytes()
    transcript_raw_path = write_immutable(
        MEDIA, candidate["item_id"], hashlib.sha256(payload).hexdigest(), ".whisper.json", payload
    )
    response = json.loads(payload)
    segments = []
    for segment in response.get("segments", []):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        segments.append({
            "segment_id": f"s{len(segments) + 1:05d}",
            "start_seconds": round(float(segment["start"]), 3),
            "end_seconds": round(float(segment["end"]), 3),
            "text": text,
        })
    if not segments:
        raise ValueError("local Whisper transcription contained no usable timed segments")
    text = " ".join(segment["text"] for segment in segments)
    details = {
        "transcript_raw_path": relative(transcript_raw_path),
        "transcription_method": "local-openai-whisper",
        "media_status": media_status,
        "media_download_method": download_method,
        "transcription_model": model_name,
        "transcription_model_sha256": file_digest(model),
    }
    return text, segments, raw_path, details


def multipart_transcription(audio_path: pathlib.Path, *, prompt: str) -> dict:
    key, _, _ = configuration()
    boundary = f"----ps04-{hashlib.sha256(audio_path.name.encode()).hexdigest()[:24]}"
    body = bytearray()

    def field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    field("model", "whisper-1")
    field("response_format", "verbose_json")
    field("timestamp_granularities[]", "segment")
    field("prompt", prompt[:1000])
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'.encode()
    )
    body.extend(b"Content-Type: audio/mpeg\r\n\r\n")
    body.extend(audio_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=bytes(body),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": USER_AGENT,
        },
    )
    USED_TOOLS.add("openai:whisper-1")
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message")
        except Exception:
            detail = None
        raise RuntimeError(f"OpenAI transcription HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI transcription connection failed: {exc.reason}") from exc


def generated_podcast_transcript(candidate: dict) -> tuple[str, list[dict], pathlib.Path]:
    if not candidate.get("media_url"):
        raise RuntimeError("podcast has neither a published transcript nor an audio enclosure")
    try:
        configuration()
    except OpenAIRequestError as exc:
        raise RuntimeError(
            "podcast has no published transcript; configure OPENAI_API_KEY to generate one from audio"
        ) from exc
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to segment podcast audio for transcription")
    USED_TOOLS.add("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="ps04-podcast-") as temporary:
        temp = pathlib.Path(temporary)
        suffix = pathlib.Path(urllib.parse.urlparse(candidate["media_url"]).path).suffix.lower()
        if suffix not in {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}:
            suffix = ".mp3"
        audio_path = temp / f"source{suffix}"
        download_to_file(candidate["media_url"], audio_path)
        raw_digest = file_digest(audio_path)
        raw_path = write_immutable_file(MEDIA, candidate["item_id"], raw_digest, suffix, audio_path)
        chunk_template = temp / "chunk-%03d.mp3"
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio_path),
                "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-f", "segment",
                "-segment_time", "1200", "-reset_timestamps", "1", str(chunk_template),
            ],
            cwd=ROOT, text=True, capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg podcast segmentation failed: {result.stderr.strip()[-500:]}")
        chunks = sorted(temp.glob("chunk-*.mp3"))
        if not chunks:
            raise RuntimeError("ffmpeg produced no podcast chunks")
        segments = []
        raw_responses = []
        prompt = (
            f"Podcast titled {candidate.get('title', '')}. Domain terms may include AI, data centers, "
            "commercial real estate, PropTech, utilities, power grids, zoning, construction, and finance."
        )
        for chunk_index, chunk in enumerate(chunks):
            response = multipart_transcription(chunk, prompt=prompt)
            raw_responses.append(response)
            for segment in response.get("segments") or []:
                text = str(segment.get("text", "")).strip()
                if not text:
                    continue
                offset = chunk_index * 1200
                segments.append({
                    "segment_id": f"s{len(segments) + 1:05d}",
                    "start_seconds": round(float(segment.get("start", 0)) + offset, 3),
                    "end_seconds": round(float(segment.get("end", 0)) + offset, 3),
                    "text": text,
                })
        if not segments:
            raise RuntimeError("OpenAI transcription returned no timestamped segments")
        transcript_payload = (json.dumps(raw_responses, ensure_ascii=False) + "\n").encode("utf-8")
        transcript_digest = hashlib.sha256(transcript_payload).hexdigest()
        write_immutable(MEDIA, candidate["item_id"], transcript_digest, ".transcription.json", transcript_payload)
    return " ".join(segment["text"] for segment in segments), segments, raw_path


def podcast_transcript(candidate: dict) -> tuple[str, list[dict], pathlib.Path]:
    transcript_url = candidate.get("transcript_url")
    if not transcript_url:
        return generated_podcast_transcript(candidate)
    payload, _, _ = fetch(transcript_url)
    suffix = pathlib.Path(urllib.parse.urlparse(transcript_url).path).suffix or ".txt"
    digest = hashlib.sha256(payload).hexdigest()
    raw_path = write_immutable(MEDIA, candidate["item_id"], digest, suffix, payload)
    decoded = payload.decode("utf-8", errors="replace")
    segments = parse_timed_text(decoded)
    if not segments:
        raise ValueError("published podcast transcript has no usable SRT/VTT timestamps")
    text = " ".join(segment["text"] for segment in segments)
    return text, segments, raw_path


def media_item(candidate: dict) -> dict:
    reused = reuse_media(candidate)
    if reused is not None:
        return reused
    if candidate["kind"] == "youtube":
        text, segments, raw_path, details = youtube_transcript(candidate)
    else:
        text, segments, raw_path = podcast_transcript(candidate)
        details = {}
    text_payload = (text.strip() + "\n").encode("utf-8")
    text_digest = hashlib.sha256(text_payload).hexdigest()
    text_path = write_immutable(ASSETS, candidate["item_id"], text_digest, ".txt", text_payload)
    segments_payload = (json.dumps(segments, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    segments_digest = hashlib.sha256(segments_payload).hexdigest()
    segments_path = write_immutable(ASSETS, candidate["item_id"], segments_digest, ".segments.json", segments_payload)
    item = dict(candidate)
    item.update({
        "text_path": relative(text_path),
        "segments_path": relative(segments_path),
        "raw_path": relative(raw_path),
    })
    item.update(details)
    item["version_id"] = compute_version(item, text, segments)
    return item


def compute_version(item: dict, text: str, segments: list[dict] | None) -> str:
    evidence = {
        "title": item.get("title"),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "text": text,
        "segments": segments,
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--errors", required=True)
    parser.add_argument("--counts", required=True)
    parser.add_argument("--metadata", required=True)
    args = parser.parse_args()

    candidates = []
    try:
        for number, line in enumerate(pathlib.Path(args.input).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            candidate = json.loads(line)
            if not isinstance(candidate, dict):
                raise ValueError(f"line {number} is not an object")
            for field in ("item_id", "source_id", "publisher_id", "kind", "title", "url", "published_at", "retrieved_at", "media_url"):
                if field not in candidate:
                    raise ValueError(f"line {number} missing {field}")
            if candidate["kind"] not in {"feed", "youtube", "podcast"}:
                raise ValueError(f"line {number} has unsupported kind")
            candidates.append(candidate)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid candidate input: {exc}", file=sys.stderr)
        return 2

    ASSETS.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    items = []
    errors = []
    for candidate in candidates:
        try:
            item = article_item(candidate) if candidate["kind"] == "feed" else media_item(candidate)
            items.append(item)
        except Exception as exc:
            errors.append({
                "item_id": candidate["item_id"],
                "source_id": candidate["source_id"],
                "kind": candidate["kind"],
                "error": f"{type(exc).__name__}: {exc}",
            })

    with pathlib.Path(args.output).open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, separators=(",", ":"), ensure_ascii=False) + "\n")
    pathlib.Path(args.errors).write_text(json.dumps(errors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pathlib.Path(args.counts).write_text(f"{len(candidates)} {len(items)} {len(errors)}\n", encoding="utf-8")
    media_gaps = [
        {"item_id": item["item_id"], "reason": item["media_download_error"], "fallback": "youtube-captions"}
        for item in items if item.get("media_status") == "transcript_only" and item.get("media_download_error")
    ]
    pathlib.Path(args.metadata).write_text(
        json.dumps({
            "tools_or_models": sorted(USED_TOOLS),
            "cost_usd": None if any(x.startswith("openai:") for x in USED_TOOLS) else 0,
            "media_gap_count": len(media_gaps),
            "media_gaps": media_gaps,
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
