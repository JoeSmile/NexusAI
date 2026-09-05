"""Task 89 M2 — 同会话 cold 不进 prompt，只注入其他会话 / 无 session 摘要。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from packages.database.pgvector_session import ChatMessage, ChatSession, ColdMemory
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
    ColdMemory.__table__.create(engine)
    sf = _SF(engine)
    monkeypatch.setattr("packages.memory.memory_service.get_pg_session", lambda: sf)
    return sf


@pytest.mark.asyncio
async def test_same_session_cold_not_loaded_for_prompt(mem_sqlite: _SF) -> None:
    svc = UnifiedMemoryService(tenant_id="t1")
    await svc.write_cold(user_id="u1", session_id="s1", summary="本会话摘要不该进当前 prompt")
    await svc.write_cold(user_id="u1", session_id="s2", summary="上个会话谈过报销")
    await svc.write_cold(user_id="u1", session_id=None, summary="跨会话用户级摘要")

    bundle = await svc.read(
        user_id="u1",
        session_id="s1",
        hot_limit=10,
        include_warm=False,
        include_cold=True,
        cold_limit=10,
    )
    summaries = [c["summary"] for c in bundle.cold]
    assert "本会话摘要不该进当前 prompt" not in summaries
    assert "上个会话谈过报销" in summaries
    assert "跨会话用户级摘要" in summaries

    text = svc.assemble_prompt_block(
        bundle, context_window_tokens=8000, budget_ratio=1.0, include_hot=False
    )
    assert "本会话摘要不该进当前 prompt" not in text
    assert "上个会话谈过报销" in text
    assert "跨会话用户级摘要" in text


@pytest.mark.asyncio
async def test_read_without_session_keeps_all_cold(mem_sqlite: _SF) -> None:
    svc = UnifiedMemoryService(tenant_id="t1")
    await svc.write_cold(user_id="u1", session_id="s1", summary="会话s1浓缩")
    bundle = await svc.read(
        user_id="u1",
        session_id=None,
        hot_limit=10,
        include_warm=False,
        include_cold=True,
        cold_limit=10,
    )
    assert any(c["summary"] == "会话s1浓缩" for c in bundle.cold)
