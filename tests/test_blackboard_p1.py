"""Task 61-s3 P1 — topic registry, conflict preprocess, blackboard_search."""

from __future__ import annotations

import pytest

from backend.core.plan.blackboard import Blackboard
from backend.core.plan.blackboard_preprocess import preprocess_blackboard_write
from backend.core.plan.topic_registry import TopicRegistryError, topic_allowed, validate_topic


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.core.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


def test_topic_registry_core_and_prefix() -> None:
    assert validate_topic("slots.missing") == "slots.missing"
    assert validate_topic("summary.weekly") == "summary.weekly"
    assert validate_topic("step.s1") == "step.s1"
    assert not topic_allowed("random.topic")
    with pytest.raises(TopicRegistryError):
        validate_topic("random.topic")


def test_preprocess_dedup_identical() -> None:
    bb = Blackboard()
    bb.add_topic(
        topic="step.s1",
        fact_content="结论A",
        source_agent_id="a",
        confidence=0.9,
    )
    ok = bb.add_topic(
        topic="step.s1",
        fact_content="结论A",
        source_agent_id="b",
        confidence=0.95,
    )
    assert ok is False
    assert len(bb.list_entries()) == 1


def test_preprocess_confidence_suppress() -> None:
    bb = Blackboard()
    bb.add_topic(
        topic="step.s1",
        fact_content="高置信结论",
        source_agent_id="a",
        confidence=0.9,
    )
    ok = bb.add_topic(
        topic="step.s1",
        fact_content="低置信不同结论",
        source_agent_id="b",
        confidence=0.3,
    )
    assert ok is False
    assert bb.list_entries()[0]["fact_content"] == "高置信结论"


def test_preprocess_semantic_conflict() -> None:
    bb = Blackboard()
    bb.add_topic(
        topic="step.s1",
        fact_content="产品定价 99 元",
        source_agent_id="a",
        confidence=0.8,
    )
    ok = bb.add_topic(
        topic="step.s1",
        fact_content="产品定价 199 元",
        source_agent_id="b",
        confidence=0.85,
    )
    assert ok is True
    entry = bb.list_entries()[0]
    assert entry["status"] == "conflict"


def test_preprocess_homogeneous_merge() -> None:
    from backend.core.plan.blackboard import BlackboardEntry

    prev = BlackboardEntry(
        source_agent_id="a",
        document_ids_ref=["d1"],
        fact_content="NexusAI 是企业级 LLM 网关",
        confidence=0.6,
        topic="step.s1",
    )
    pre = preprocess_blackboard_write(
        topic="step.s1",
        fact_content="NexusAI 是企业级网关",
        confidence=0.7,
        document_ids_ref=["d2"],
        prev=prev,
    )
    assert pre.action == "homogeneous_merge"
    assert "d1" in (pre.document_ids_ref or [])
    assert "d2" in (pre.document_ids_ref or [])


def test_blackboard_search_by_topic_and_keyword() -> None:
    bb = Blackboard()
    bb.add_topic(
        topic="summary.weekly",
        fact_content="本周热点：AI 网关",
        source_agent_id="a",
        confidence=0.8,
    )
    bb.add_topic(
        topic="step.s2",
        fact_content="执行完成",
        source_agent_id="b",
        confidence=0.9,
    )
    hits = bb.search(topic="summary.", keyword="网关")
    assert len(hits) == 1
    assert hits[0]["topic"] == "summary.weekly"


@pytest.mark.asyncio
async def test_blackboard_search_builtin_handler() -> None:
    from backend.core.auth.models import TenantContext
    from backend.core.capability.builtin.handlers import invoke_builtin_handler

    tenant = TenantContext("t1", "u1", "user", ["chat:read"], False)
    payload = {
        "blackboard": [
            {
                "topic": "step.s1",
                "fact_content": "检索命中 3 条",
                "source_agent_id": "s1:rag.search",
                "document_ids_ref": [],
                "confidence": 0.9,
                "status": "active",
                "version": 1,
            }
        ],
        "keyword": "检索",
    }
    result = await invoke_builtin_handler("blackboard.search", payload, tenant)
    assert result["ok"] is True
    assert result["count"] == 1
