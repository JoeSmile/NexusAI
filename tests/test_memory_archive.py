"""Task 78.1 — chat_messages.archived_at + unarchived hot reads."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from packages.database.pgvector_session import ChatMessage, ChatSession
from packages.memory.memory_service import UnifiedMemoryService
from packages.memory.turn_archive import select_turn_ids_to_archive
from packages.pipeline.context_messages import CONTEXT_TOKEN_BUDGET, HOT_HISTORY_TURNS
from tests.memory_sqlite import sqlite_memory_engine


def test_chat_message_archived_at_is_nullable() -> None:
    col = ChatMessage.__table__.c.archived_at
    assert col.nullable is True


def test_select_oldest_overflow_by_turn_count() -> None:
    rows = [(i, f"m{i}") for i in range(12)]
    ids = select_turn_ids_to_archive(
        rows, max_turns=HOT_HISTORY_TURNS, budget_tokens=CONTEXT_TOKEN_BUDGET
    )
    assert ids == [0, 1]


def test_select_oldest_overflow_by_token_budget() -> None:
    rows = [(1, "a" * 40), (2, "b" * 40), (3, "keep")]
    ids = select_turn_ids_to_archive(rows, max_turns=10, budget_tokens=20)
    assert 1 in ids
    assert 3 not in ids


def test_select_overflow_empty_when_under_window() -> None:
    rows = [(1, "hi"), (2, "there")]
    assert (
        select_turn_ids_to_archive(
            rows, max_turns=HOT_HISTORY_TURNS, budget_tokens=CONTEXT_TOKEN_BUDGET
        )
        == []
    )


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
    monkeypatch.setattr(
        "packages.memory.memory_service.get_pg_session", lambda: sf
    )
    return sf


@pytest.mark.asyncio
async def test_write_turn_leaves_archived_at_null(mem_sqlite: _SF) -> None:
    svc = UnifiedMemoryService(tenant_id="t1")
    await svc.write_turn(
        user_id="u1",
        session_id="s1",
        user_message="hello",
        assistant_message="hi",
    )
    with mem_sqlite.Session() as session:
        rows = session.query(ChatMessage).order_by(ChatMessage.id.asc()).all()
    assert len(rows) == 2
    assert all(r.archived_at is None for r in rows)


@pytest.mark.asyncio
async def test_hot_read_skips_archived_rows(mem_sqlite: _SF) -> None:
    svc = UnifiedMemoryService(tenant_id="t1")
    await svc.write_turn(
        user_id="u1",
        session_id="s1",
        user_message="old",
        assistant_message="old-a",
    )
    await svc.write_turn(
        user_id="u1",
        session_id="s1",
        user_message="new",
        assistant_message="new-a",
    )
    with mem_sqlite.Session() as session:
        oldest = (
            session.query(ChatMessage).order_by(ChatMessage.created_at.asc()).first()
        )
        assert oldest is not None
        oldest.archived_at = datetime.utcnow()
        session.commit()
    bundle = await svc.read(
        user_id="u1", session_id="s1", hot_limit=20, include_warm=False, include_cold=False
    )
    texts = [m["content"] for m in bundle.hot]
    assert "old" not in texts
    assert "new" in texts
    assert "new-a" in texts


@pytest.mark.asyncio
async def test_write_turn_archives_oldest_over_turn_window(
    mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORY_ARCHIVE_MAX_TURNS", "4")
    monkeypatch.setenv("MEMORY_ARCHIVE_TOKEN_BUDGET", "8000")
    svc = UnifiedMemoryService(tenant_id="t1")
    for i in range(3):
        await svc.write_turn(
            user_id="u1",
            session_id="s1",
            user_message=f"u{i}",
            assistant_message=f"a{i}",
        )
    with mem_sqlite.Session() as session:
        rows = session.query(ChatMessage).order_by(ChatMessage.id.asc()).all()
    assert len(rows) == 6
    archived = [r.content for r in rows if r.archived_at is not None]
    live = [r.content for r in rows if r.archived_at is None]
    assert archived == ["u0", "a0"]
    assert live == ["u1", "a1", "u2", "a2"]
    bundle = await svc.read(
        user_id="u1", session_id="s1", hot_limit=20, include_warm=False, include_cold=False
    )
    assert [m["content"] for m in bundle.hot] == live


def test_mem_sqlite_visible_from_worker_thread(mem_sqlite: _SF) -> None:
    """T0: StaticPool so asyncio.to_thread readers see the same sqlite."""
    from concurrent.futures import ThreadPoolExecutor

    with mem_sqlite.Session() as session:
        session.add(ChatSession(session_id="s-thread", tenant_id="t1", user_id="u1", title="x"))
        session.commit()

    def _count() -> int:
        with mem_sqlite.Session() as session:
            return session.query(ChatSession).filter_by(session_id="s-thread").count()

    with ThreadPoolExecutor(max_workers=1) as pool:
        n = pool.submit(_count).result(timeout=5)
    assert n == 1
