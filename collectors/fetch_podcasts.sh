#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"
# shellcheck source=lib/collector_runner.sh
source "$ROOT/lib/collector_runner.sh"

if [[ "$#" -ne 1 ]]; then
  printf 'usage: bash collectors/fetch_podcasts.sh RUN_DIR\n' >&2
  exit 2
fi
ps04_run_syndication_collector "$1" "podcast" "fetch-podcasts"
