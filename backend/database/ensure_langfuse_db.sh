#!/bin/sh
# 在共享 Postgres 上确保存在独立的 langfuse 库（不污染 contextgate schema）
set -eu
HOST="${POSTGRES_HOST:-postgres}"
USER="${POSTGRES_USER:-contextgate}"
DB="${POSTGRES_DB:-contextgate}"
export PGPASSWORD="${POSTGRES_PASSWORD:-contextgate_local}"

until pg_isready -h "$HOST" -U "$USER" -d "$DB" >/dev/null 2>&1; do
  sleep 1
done

exists=$(psql -h "$HOST" -U "$USER" -d "$DB" -tAc "SELECT 1 FROM pg_database WHERE datname='langfuse'")
if [ "$exists" != "1" ]; then
  psql -h "$HOST" -U "$USER" -d "$DB" -c "CREATE DATABASE langfuse"
  echo "created database langfuse"
else
  echo "database langfuse already exists"
fi
