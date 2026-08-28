"""Task 73 slice 3 — UVICORN_WORKERS 与 PG 连接池核算。"""

from __future__ import annotations

import pytest

from packages.uvicorn_workers import resolve_uvicorn_workers
from backend.database.pg_pool import pg_engine_kwargs, pg_pool_budget_note


def test_reload_forces_one_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UVICORN_WORKERS", "4")
    monkeypatch.setenv("API_WORKERS", "8")
    assert resolve_uvicorn_workers(reload=True) == 1


def test_workers_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UVICORN_WORKERS", "3")
    assert resolve_uvicorn_workers(reload=False) == 3


def test_workers_falls_back_to_api_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    monkeypatch.setenv("API_WORKERS", "2")
    assert resolve_uvicorn_workers(reload=False) == 2


def test_workers_default_is_one_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    monkeypatch.delenv("API_WORKERS", raising=False)
    assert resolve_uvicorn_workers(reload=False) == 1


def test_pg_engine_kwargs_pre_ping_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "7")
    kw = pg_engine_kwargs("postgresql://nexusai:x@localhost:5432/nexusai")
    assert kw["pool_pre_ping"] is True
    assert kw["pool_size"] == 5
    assert kw["max_overflow"] == 7


def test_pg_engine_kwargs_sqlite_skips_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    kw = pg_engine_kwargs("sqlite:///:memory:")
    assert "pool_size" not in kw
    assert kw["connect_args"]["check_same_thread"] is False


def test_pool_budget_note_contains_formula() -> None:
    note = pg_pool_budget_note(workers=3, pool_size=5, max_overflow=10, extras=8)
    assert "3" in note and "5" in note
    assert "<" in note
    assert str(3 * (5 + 10) + 8) in note
