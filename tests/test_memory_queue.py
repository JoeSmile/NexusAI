"""S2c/S2d/S2e smoke tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.memory import memory_queue as mq
from backend.core.memory.extractor import is_async_key, is_sync_key
from backend.core.memory_service import MemoryBundle, UnifiedMemoryService, _student_alias


def test_enqueue_degrades_without_redis(monkeypatch):
    monkeypatch.setattr(mq, "_client", lambda: None)
    assert mq.enqueue_memory_write({"tenant_id": "t", "user_id": "u", "key": "k", "value": "v"}) is None


def test_enqueue_and_tombstone(monkeypatch):
    store: dict[str, str] = {}
    fake = MagicMock()
    fake.xgroup_create.side_effect = Exception("BUSYGROUP")
    fake.xlen.return_value = 0
    fake.xadd.return_value = "1-0"
    fake.xrange.return_value = []
    fake.set = lambda k, v, ex=None: store.__setitem__(k, v) or True
    fake.get = lambda k: store.get(k)
    monkeypatch.setattr(mq, "_client", lambda: fake)
    xid = mq.enqueue_memory_write(
        {"tenant_id": "t", "user_id": "u", "key": "entity:x", "value": "{}"}
    )
    assert xid == "1-0"
    assert mq.tombstone_user("t", "u") is True
    assert mq.is_tombstoned("t", "u") is True


def test_tombstone_fail_closed_without_redis(monkeypatch):
    monkeypatch.setattr(mq, "_client", lambda: None)
    assert mq.tombstone_user("t", "u") is False
    assert mq.is_tombstoned("t", "u") is None


def test_is_sync_key_matrix():
    assert is_sync_key("identity:x")
    assert is_sync_key("todo:x")
    assert is_sync_key("pending:s:他")
    assert not is_sync_key("entity:x")
    assert is_async_key("decision:y")
    assert is_async_key("error:E-1")


def test_student_alias_stable():
    a1 = _student_alias(tenant_id="t1", name="张三", key="entity:张三")
    a2 = _student_alias(tenant_id="t1", name="张三", key="entity:张三")
    b1 = _student_alias(tenant_id="t2", name="张三", key="entity:张三")
    assert a1 == a2
    assert a1.startswith("学生")
    assert b1.startswith("学生")


def test_assemble_redacts_student_entity():
    svc = UnifiedMemoryService(tenant_id="t")
    warm = {
        "entity:张三": json.dumps(
            {"name": "张三", "relation": "学生", "text": "张三", "type": "person"}
        )
    }
    block = svc.assemble_prompt_block(
        MemoryBundle(warm=warm),
        query="",  # no filter → include all world when query empty
    )
    assert "学生" in block
    assert "张三" not in block


@pytest.mark.asyncio
async def test_memory_hub_retrieve_uses_unified():
    from backend.agent.memory_hub import MemoryHub
    from backend.core.memory_service import MemoryBundle

    hub = MemoryHub(user_id="u1", session_id="s1", tenant_id="t1")
    fake_mem = MagicMock()
    fake_mem.read = AsyncMock(
        return_value=MemoryBundle(warm={"fact:x": "hello"}, hot=[], cold=[])
    )
    fake_mem.assemble_prompt_block = MagicMock(return_value="# 用户背景\n- fact:x")
    with patch(
        "backend.core.memory_service.get_unified_memory_service",
        return_value=fake_mem,
    ):
        out = await hub.retrieve("hello", user_id="u1")
    assert out
    assert "用户背景" in out[0]["content"] or out[0]["scope"] == "unified"
    fake_mem.read.assert_awaited()


def test_drop_poison_acks(monkeypatch):
    acked: list[str] = []
    monkeypatch.setattr(mq, "ack", lambda xid: acked.append(xid))
    with patch("backend.core.audit.write_audit_sync"):
        with patch("backend.core.metrics_memory.record_dropped"):
            mq.drop_poison("9-0", {"tenant_id": "t", "user_id": "u", "key": "entity:x"}, deliveries=4)
    assert acked == ["9-0"]


@pytest.mark.asyncio
async def test_persist_warm_async_enqueues(monkeypatch):
    from backend.core.memory.write_items import persist_warm_by_key

    mem = MagicMock()
    mem.write = AsyncMock()
    monkeypatch.setattr(
        "backend.core.memory.memory_queue.enqueue_memory_write",
        lambda payload: "1-0",
    )
    monkeypatch.setattr(
        "backend.core.memory.memory_queue.queue_depth",
        lambda: 1,
    )
    status = await persist_warm_by_key(
        mem,
        tenant_id="t",
        user_id="u",
        key="entity:foo",
        value="{}",
        confidence=0.9,
        source="test",
    )
    assert status == "queued"
    mem.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_warm_degraded_fallback(monkeypatch):
    from backend.core.memory.write_items import persist_warm_by_key

    mem = MagicMock()
    mem.write = AsyncMock()
    monkeypatch.setattr(
        "backend.core.memory.memory_queue.enqueue_memory_write",
        lambda payload: None,
    )
    status = await persist_warm_by_key(
        mem,
        tenant_id="t",
        user_id="u",
        key="decision:bar",
        value="{}",
        confidence=0.9,
        source="test",
    )
    assert status == "degraded"
    mem.write.assert_awaited()
