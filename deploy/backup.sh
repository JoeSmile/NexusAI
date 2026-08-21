#!/usr/bin/env bash
# Task 52 P0-2 — dump Postgres to data/backups/ and keep 14 newest.
# Non-zero exit on failure (wire to cron mail / log).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTDIR="${BACKUP_DIR:-$ROOT/data/backups}"
KEEP="${BACKUP_KEEP:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/docker-compose.prod.yml}"
STAMP="$(date +%Y%m%d)"
mkdir -p "$OUTDIR"
DEST="$OUTDIR/nexusai-${STAMP}.sql.gz"

if [[ -n "${PG_CONTAINER:-}" ]]; then
  CONTAINER="$PG_CONTAINER"
else
  CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps -q postgres)"
fi

if [[ -z "$CONTAINER" ]]; then
  echo "backup failed: postgres container not found" >&2
  exit 1
fi

echo "dumping postgres ($CONTAINER) -> $DEST"
docker exec "$CONTAINER" pg_dump -U nexusai -d nexusai | gzip -c > "$DEST"
if [[ ! -s "$DEST" ]]; then
  echo "backup failed: empty dump $DEST" >&2
  rm -f "$DEST"
  exit 1
fi

python3 "$ROOT/scripts/prune_backups.py" --dir "$OUTDIR" --keep "$KEEP"
echo "backup ok: $DEST"
