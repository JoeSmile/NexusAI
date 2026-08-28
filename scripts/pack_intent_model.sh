#!/usr/bin/env bash
# Pack intent_v8 model tree as a separate deploy artifact.
# Requires local data/models/intent_v8 (not in git).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SRC="data/models/intent_v8"
if [[ ! -f "$SRC/config.json" ]]; then
  echo "ERROR: $SRC/config.json not found. Copy/train the model first (scripts/copy_intent_model.py)." >&2
  exit 1
fi

mkdir -p artifacts
OUT="artifacts/intent_v8.tar.gz"
tar -czf "$OUT" -C data/models intent_v8
echo "Wrote $OUT"
tar -tzf "$OUT" | head -n 20
