#!/usr/bin/env bash
# Pilot B 8 gold-line wrapper
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export SMOKE_BASE_URL="${SMOKE_BASE_URL:-http://127.0.0.1:8000}"
uv run python examples/qa/journeys/pilot_b_8_gold_line.py
