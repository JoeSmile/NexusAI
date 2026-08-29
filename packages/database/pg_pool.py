"""PostgreSQL 连接池参数（Task 73 切片 3）。

每进程一份池。总占用：

    (DB_POOL_SIZE + DB_MAX_OVERFLOW) × UVICORN_WORKERS
    + memory-worker / social-worker / alembic / 扫描器 extras
    < Postgres max_connections（默认 100，须留余量）
"""

from __future__ import annotations

import os
from typing import Any


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def pg_pool_size() -> int:
    return max(1, _env_int("DB_POOL_SIZE", 10))


def pg_max_overflow() -> int:
    return max(0, _env_int("DB_MAX_OVERFLOW", 20))


def pg_pool_recycle() -> int:
    return max(60, _env_int("DB_POOL_RECYCLE", 3600))


def pg_engine_kwargs(db_url: str) -> dict[str, Any]:
    if db_url.startswith("sqlite"):
        return {"echo": False, "connect_args": {"check_same_thread": False}}
    return {
        "echo": False,
        "pool_pre_ping": True,
        "pool_size": pg_pool_size(),
        "max_overflow": pg_max_overflow(),
        "pool_recycle": pg_pool_recycle(),
    }


def pg_pool_budget_note(
    *,
    workers: int,
    pool_size: int,
    max_overflow: int,
    extras: int,
) -> str:
    total = workers * (pool_size + max_overflow) + extras
    return (
        f"pool_size({pool_size}) × workers({workers}) + overflow({max_overflow}×{workers}) "
        f"+ extras({extras}) = {total} < max_connections"
    )
