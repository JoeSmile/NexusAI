#!/usr/bin/env bash
# White-list release tarball for NexusAI deploy hosts.
# Requires: bash, tar, git (optional). Run from repo root or any cwd.
# Windows: use Git Bash or WSL — not PowerShell.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p artifacts

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if command -v git >/dev/null 2>&1 && git rev-parse --short HEAD >/dev/null 2>&1; then
  STAMP="$(git rev-parse --short HEAD)-${STAMP}"
fi
OUT="artifacts/nexusai-release-${STAMP}.tar.gz"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/nexusai-pack.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

copy_if() {
  local src="$1"
  if [[ -e "$src" ]]; then
    mkdir -p "$STAGE/$(dirname "$src")"
    cp -a "$src" "$STAGE/$src"
  fi
}

copy_tree_if() {
  local src="$1"
  if [[ -d "$src" ]]; then
    mkdir -p "$STAGE/$(dirname "$src")"
    cp -a "$src" "$STAGE/$src"
  fi
}

# --- whitelist ---
copy_tree_if backend
copy_tree_if packages
copy_tree_if apps
copy_tree_if alembic
copy_tree_if deploy
copy_if alembic.ini
copy_if config.py
copy_if pyproject.toml
copy_if uv.lock
copy_if Dockerfile
copy_if docker-compose.prod.yml
copy_if docker-compose.langfuse.yml
copy_if config.env.example
copy_if .env.example
copy_if README.md
copy_if AGENTS.md
copy_if docs/DEPLOYMENT.md
copy_if docs/REPO_LAYOUT.md

if [[ -d frontend/dist ]] && [[ -n "$(ls -A frontend/dist 2>/dev/null || true)" ]]; then
  mkdir -p "$STAGE/frontend"
  cp -a frontend/dist "$STAGE/frontend/dist"
else
  echo "WARN: frontend/dist missing or empty — run: cd frontend && pnpm build" >&2
fi

# Strip junk that may have been copied with trees
find "$STAGE" -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name 'node_modules' -o -name '.venv' \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -type f \( -name '*.pyc' -o -name '.tmp_*' -o -name '*.log' \) -delete 2>/dev/null || true
# Never ship secrets / local data
rm -rf "$STAGE/config.env" "$STAGE/.env" "$STAGE/uploads" "$STAGE/data" "$STAGE/log" 2>/dev/null || true

tar -C "$STAGE" -czf "$OUT" .
echo "Wrote $OUT"
COUNT="$(tar -tzf "$OUT" | wc -l | tr -d ' ')"
echo "entries: $COUNT"
tar -tzf "$OUT" | grep -q '^backend/' || { echo "ERROR: backend/ missing from tarball" >&2; exit 1; }
tar -tzf "$OUT" | grep -q '^deploy/' || { echo "ERROR: deploy/ missing from tarball" >&2; exit 1; }
if tar -tzf "$OUT" | grep -E '\.venv/|node_modules/' >/dev/null; then
  echo "ERROR: tarball contains .venv or node_modules" >&2
  exit 1
fi
echo "OK: pack_release checks passed"
