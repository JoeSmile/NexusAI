"""Shared in-memory SQLite for memory tests (T0: to_thread-safe).

Default ``sqlite:///:memory:`` + SingletonThreadPool gives each worker
thread an empty database. StaticPool + check_same_thread=False keeps one
connection for the whole fixture lifetime.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool


def sqlite_memory_engine() -> Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
