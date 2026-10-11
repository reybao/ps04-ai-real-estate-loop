#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$#" -eq 1 ]] || { printf 'usage: bash publishing/prepare_package.sh RUN_DIR\n' >&2; exit 2; }
exec python3 "$ROOT/publishing/prepare_package.py" "$1"
