#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="${PS04_PYTHON:-python3.13}"
VENV="$ROOT/tmp/whisper-venv"
MODEL_DIR="$ROOT/data/models"
MODEL="$MODEL_DIR/small.en.pt"
EXPECTED_SHA256="f953ad0fd29cacd07d5a9eda5624af0f6bcf2258be67c92b79389873d91e0872"
MODEL_URL="https://openaipublic.azureedge.net/main/whisper/models/$EXPECTED_SHA256/small.en.pt"

command -v "$PYTHON" >/dev/null || { printf 'Python not found: %s\n' "$PYTHON" >&2; exit 1; }
command -v ffmpeg >/dev/null || { printf 'ffmpeg is required\n' >&2; exit 1; }
command -v curl >/dev/null || { printf 'curl is required\n' >&2; exit 1; }

if [[ ! -x "$VENV/bin/whisper" ]]; then
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --no-cache-dir 'openai-whisper==20250625'
fi

mkdir -p "$MODEL_DIR"
if [[ -f "$MODEL" ]] && printf '%s  %s\n' "$EXPECTED_SHA256" "$MODEL" | shasum -a 256 -c - >/dev/null; then
  printf 'Local Whisper small.en is ready.\n'
  exit 0
fi

PART="$MODEL.part"
curl -L --fail --retry 3 --output "$PART" "$MODEL_URL"
printf '%s  %s\n' "$EXPECTED_SHA256" "$PART" | shasum -a 256 -c - >/dev/null || {
  printf 'Downloaded model failed SHA-256 verification.\n' >&2
  exit 1
}
mv "$PART" "$MODEL"
printf 'Local Whisper small.en is ready.\n'
