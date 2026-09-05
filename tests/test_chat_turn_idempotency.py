"""Task 84 S2 — chat turn idempotency by client_message_id."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

from packages.database.pgvector_session import ChatMessage, ChatSession
from packages.memory.memory_service import UnifiedMemoryService
from tests.memory_sqlite import sqlite_memory_engine


class _SF:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.Session = sessionmaker(bind=engine)


@pytest.fixture()
def mem_sqlite(monkeypatch: pytest.MonkeyPatch) -> _SF:
    engine = sqlite_memory_engine()
    ChatSession.__table__.create(engine)
    ChatMessage.__table__.create(engine)
    sf = _SF(engine)
    monkeypatch.setattr("packages.memory.memory_service.get_pg_session", lambda: sf)
    return sf


@pytest.mark.asyncio
async def test_write_turn_same_client_ids_inserts_once(mem_sqlite: _SF) -> None:
    svc = UnifiedMemoryService(tenant_id="t1")
    kwargs = dict(
        user_id="u1",
        session_id="s1",
        user_message="hi",
        assistant_message="hello",
        user_client_message_id="cid-user",
        assistant_client_message_id="cid-asst",
    )
    first = await svc.write_turn(**kwargs)
    second = await svc.write_turn(**kwargs)
    assert first["wrote_user"] is True
    assert first["wrote_assistant"] is True
    assert second["duplicate"] is True
    assert second["wrote_user"] is False
    assert second["wrote_assistant"] is False
    with mem_sqlite.Session() as session:
        rows = session.query(ChatMessage).order_by(ChatMessage.id.asc()).all()
    assert len(rows) == 2
    assert [r.role for r in rows] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_write_turn_missing_client_id_still_inserts(mem_sqlite: _SF) -> None:
    svc = UnifiedMemoryService(tenant_id="t1")
    await svc.write_turn(
        user_id="u1",
        session_id="s1",
        user_message="a",
        assistant_message="b",
    )
    await svc.write_turn(
        user_id="u1",
        session_id="s1",
        user_message="a",
        assistant_message="b",
    )
    with mem_sqlite.Session() as session:
        assert session.query(ChatMessage).count() == 4


@pytest.mark.asyncio
async def test_write_memory_skips_audit_on_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.pipeline.nodes import write_memory as wm

    async def _dup(**_k):
        return {
            "duplicate": True,
            "wrote_user": False,
            "wrote_assistant": False,
            "archived_ids": [],
        }

    mem = SimpleNamespace(
        write_turn=_dup,
        read=MagicMock(),
        maybe_cold_summarize=MagicMock(),
    )
    monkeypatch.setattr(wm, "get_unified_memory_service", lambda **_k: mem)

    class _Sess:
        def execute(self, *_a, **_k):
            raise AssertionError("audit insert must not run on duplicate turn")

        def commit(self) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _SF:
        def Session(self):
            return _Sess()

    monkeypatch.setattr(wm, "get_pg_session", lambda: _SF())

    state = {
        "tenant_id": "t1",
        "user_id": "u1",
        "session_id": "s1",
        "message": "hi",
        "response": "hello",
        "trace_id": "tr1",
        "user_client_message_id": "cid-user",
        "assistant_client_message_id": "cid-asst",
        "total_cost": 1.23,
    }
    out = await wm.write_memory(state)
    assert out["trace_id"] == "tr1"
    mem.maybe_cold_summarize.assert_not_called()
