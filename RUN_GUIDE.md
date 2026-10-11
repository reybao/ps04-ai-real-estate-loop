# PS04 Run and Submission Guide

## 1. Automated scope

`bash run.sh` performs the following steps in order:

1. Fix the run's actual UTC date and snapshot the configuration, editorial policy, and prompts.
2. Discover candidate material from RSS feeds, YouTube channels, and podcast feeds.
3. Retain article text; attempt to download YouTube video, retry with a 360p `android_vr` format if the default video request fails, then try audio-only if necessary. Transcribe retained media with local Python Whisper; retain platform captions with an explicit media-gap warning if all media downloads are blocked; obtain or generate timestamped podcast transcripts.
4. Store stable `item_id` and `version_id` records in SQLite without duplicating unchanged versions.
5. Apply the inclusive 30-calendar-day window relative to the run date.
6. Ask AI to `accept`, `reject`, or `defer` each eligible item, with a reason.
7. Create three briefs with claim-level evidence locators.
8. Generate three article drafts and three 3–5-minute video scripts from those briefs.
9. Check evidence locators, publisher independence, media coverage, claim IDs, dates, and approximate length.
10. Stop at `awaiting_review` when checks pass; the student makes the publication decision.

The pipeline never approves, renders, or publishes on the student's behalf.
If an AI brief fails its evidence checks, the brief stage feeds the exact error and
already accepted evidence back to the model for up to two targeted repairs. It
keeps the original response and each retry request, response, and metadata under
`runs/RUN_ID/model/`. A repaired brief is checked again before article writing;
if it still fails, the pipeline stops for human review. Repeating the affected
series stage reuses saved collection and extraction rather than downloading them
again.

For a run that already collected evidence but stopped at brief creation, resume
only the series stage, then refresh its summary (replace `RUN_ID` with the saved
run directory name):

```bash
bash workflows/create_series.sh runs/RUN_ID
bash reporting/summarize_run.sh runs/RUN_ID > runs/RUN_ID/summary.json
```

Do not start a new `bash run.sh` merely to retry a failed brief: that command
creates a separate live run and collects sources again.

## 2. Initial setup

Work from the project directory:

```bash
cd /path/to/ps04
```

For a new installation, copy `.env.example` to the Git-ignored `.env.local` and enter your own key. Do not overwrite an existing `.env.local`:

```bash
cp .env.example .env.local
```

The file uses these variable names; never include a real key in a screenshot or commit:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-6-luna
OPENAI_REASONING_EFFORT=low
```

The local tools are Bash, Python 3, SQLite, Git, `yt-dlp`, `ffmpeg`, and local Python Whisper. This development machine was checked with Bash 3.2.57, Python 3.14.8 for the pipeline, Python 3.13 for Whisper, SQLite 3.51.0, Git 2.55.0, and yt-dlp 2026.08.19. If collection or audio tools are missing on a Mac, Homebrew can install them:

```bash
brew install yt-dlp ffmpeg sqlite
```

Set up the local Whisper `small.en` model separately; this does not require an OpenAI API key. The setup helper creates an ignored Python virtual environment, installs `openai-whisper==20250625`, downloads the official `small.en` checkpoint into ignored `data/models/`, and verifies its SHA-256 hash:

```bash
bash processing/setup_local_whisper.sh
```

The default command is `tmp/whisper-venv/bin/whisper`, and the default model is `small.en`. Set `PS04_PYTHON` before setup if Python 3.13 is unavailable; set `PS04_WHISPER_CLI` or `PS04_WHISPER_MODEL` before a run only if intentionally using another local installation or model. The `OPENAI_API_KEY` above is still used by the AI editorial and writing stages, not by local YouTube transcription.

## 3. Start a live run

```bash
bash run.sh
```

The terminal prints a summary. Each run is stored under `runs/YYYYMMDDTHHMMSSZ-xxxxxx/`. Inspect these files before treating the output as publishable:

- `summary.json`: overall status, counts, coverage, unresolved stages, and unknown costs.
- `logs/`: a receipt for each component and retry.
- `extraction_errors.json`: items whose text or transcript could not be obtained; other extracted items remain usable.
- `extraction_metadata.json`: extraction tools and any YouTube media-download gaps, including the affected item IDs and fallback reason.
- `exclusions.jsonl`: mechanical exclusions for stale, unknown, future, or invalid dates.
- `decisions.jsonl`: AI accept/reject/defer decisions and reasons for every eligible item.
- `briefs.jsonl`: the three arguments, claims, source versions, and exact evidence locators.
- `articles/` and `video_scripts/`: the three draft pairs.
- `review.json`: machine-check findings and the current `review_id`.

The October 9, 2026 draft run is `runs/20261009T165149Z-afdf19/`. It predates the local-Whisper change: its YouTube evidence came from platform captions, and no YouTube video file was retained. It has three articles and three scripts, and its automated review passes, but it remains `awaiting_review`. Four YouTube candidates could not be extracted because of a not-yet-started live event, unavailable subtitles, or a subtitle rate limit. That incomplete coverage is recorded rather than hidden. No publication approval or finished videos exist for this run.

After the extractor update, local integration tests successfully retained a synthetic MP4 and a simulated audio-only fallback, producing timestamped `small.en` segments in both cases. Initial live `yt-dlp` media requests for two collected public YouTube items returned HTTP 403. Later, 10 KB `android_vr` format-18 test samples succeeded for all three cited YouTube videos, but those samples are **not** complete retained media. An isolated end-to-end check of the collected 8:36 water/electricity explainer subsequently retained a complete 18 MB MP4 and produced 137 local `small.en` timestamped segments; the default video path succeeded in that check. Its result is in `runs/replays/youtube-media-check-20261009/`, not in the first run's item records. Download success may vary by video or session, so the first run's caption-only gap remains until a later live run retains and records complete media for its cited items.

## 4. Human editorial review

The student must:

1. Check important facts, numbers, quotations, and context against the retained source text or transcript.
2. Verify that company statements are attributed and not presented as independently established outcomes.
3. Decide whether the three pieces make genuinely different arguments.
4. Review at least three `accept` decisions and three `reject` or `defer` decisions; compare the AI's reasons with the student's judgment in `SUBMISSION.md`.
5. Revise `config/editorial_policy.md` at least once, rerun the affected stage, and preserve the before/after policy and outputs.
6. Check suggested video visuals for copyright, feasibility, and misleading presentation.
7. Use only the author's own materials for an avatar or voice clone and complete the production platform's consent process.

After changing any reviewed draft, regenerate its check result:

```bash
bash review/check_content.sh runs/RUN_ID > runs/RUN_ID/review.json
```

The `review_id` changes when assessed material changes. A previous approval cannot be reused for revised content.

## 5. Record human approval only after review

For a guided human review of the three articles and their paired video scripts,
run this in the VS Code integrated terminal:

```bash
bash run.sh --approve runs/RUN_ID
```

The command shows the current check, opens each article together with its
paired video script in VS Code, and asks for a decision in the terminal after
each piece. Read the two editor tabs, then return to the terminal. Choose `1`
if no adjustment is needed, `2` if adjustment is needed (a short reason and
manual-vs-API choice are recorded, and packaging stops), or `0` to cancel without changing
the existing approval. Only three `1` decisions produce overall
approval and automatically prepare the package. Per-piece decisions, the
current `review_id`, and UTC timestamps are recorded automatically. It records
the local account name as reviewer, or uses `PS04_REVIEWER` if set. The `code`
command must be available in the terminal. If `approval.json` already exists, the previous
file is preserved under `approval_history/`. This command requires an
interactive terminal and never approves on its own.

For a small punctuation or wording correction, choose `2`, select manual
revision, edit the open Markdown file(s) in VS Code, and save. For a substantial
change, choose the API proposal option and describe the requested change. The
OpenAI API uses the existing configured key and saves its suggestion under
`runs/RUN_ID/revisions/PIECE_ID/REVISION_ID/`; it opens a VS Code diff when
available. The current article and script are never overwritten. The model
may also say the change cannot be supported by the retained evidence. Repeating
the same request and unchanged drafts reuses the saved proposal. To retry a
failed API request, run `bash run.sh --propose-revision runs/RUN_ID`.

After accepting or manually making any edit, save the Markdown files and run
`bash run.sh --approve runs/RUN_ID` again. Approve mode refreshes the automated
content check before showing the revised drafts. The new content requires a
new human approval; an earlier package is not publication ready while the
approval decision is `revise`.

The manual alternative remains available:

After personally checking and approving the final version, the student creates `runs/RUN_ID/approval.json`:

```json
{
  "review_id": "copy_the_current_review_id",
  "decision": "approve",
  "reviewer": "your_name",
  "reviewed_at": "actual_UTC_time_such_as_2026-10-09T20:00:00Z",
  "notes": "State what you checked or corrected and what limitations remain."
}
```

Use `"decision": "revise"` if changes remain necessary; the packager will refuse to proceed.

## 6. Prepare the production handoff

```bash
bash run.sh --package runs/RUN_ID
```

After a successful approval check, `runs/RUN_ID/package/` contains three article Markdown files, three video-script Markdown files, per-piece source notes, `publication_links.json`, and a manifest of remaining manual work. The packager detects stale reviews and approvals if any assessed input changed. Packaging does not create videos or publish content.

## 7. Produce videos and publish

For each of the three pieces:

1. Use the packaged video script in Google Vids or HeyGen.
2. If desired, use an authorized avatar for the opening and closing; use graphics, maps, case visuals, and readable source cards in the middle.
3. If using the author's authorized cloned voice, retain an explicit AI-generated avatar/voice disclosure.
4. Review the rendered video for factual accuracy, visuals, pronunciation, subtitles, consent, and source labeling.
5. Publish the article on Substack without a paid access requirement and the video on YouTube as public or unlisted.
6. Link the video from the article; put the article and principal source links in the video's description.
7. Enter all six publication URLs in `publication_links.json` and complete `SUBMISSION.md`.

Record a separate 4–6-minute technical demonstration video. It is not one of the three audience-facing videos.

## 8. Known limitations

- YouTube extraction first attempts the default video download, then the `android_vr` 360p video format, then audio-only. Either retained medium is transcribed locally with Python Whisper `small.en`, saving raw Whisper JSON in `data/media/` and normalized timestamped segments in `data/assets/`. A successful new item has `media_status: video_retained` or `audio_retained` and records `media_download_method`. If all media downloads fail, the extractor can retain available captions instead, marked `media_status: transcript_only` with `media_download_error`; this does not satisfy the media-retention part of the course requirement. The student must disclose or repair that gap before claiming full compliance. The October 9 first run contains legacy caption-only item records.
- Podcast extraction first uses a publisher-supplied timestamped transcript. When unavailable, the configured workflow can download audio, segment it with `ffmpeg`, and request `whisper-1` timestamps. A missing key or failed transcription is recorded as a failure; the pipeline never pretends to have listened to unavailable audio.
- A generic HTML parser may fail on paywalled, JavaScript-only, or anti-scraping pages.
- Model costs remain unknown unless a reliable pricing calculation is added; unknown cost is not reported as zero.
- Machine checks establish structure and resolvable citations, not the soundness of every interpretation. The student remains responsible for factual and editorial judgment.
