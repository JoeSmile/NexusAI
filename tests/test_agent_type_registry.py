"""Task 62 — AgentType registry + intent mapping."""

from __future__ import annotations

from backend.core.plan.agent_type import (
    agent_type_for_intent,
    get_agent_type,
    list_agent_types,
)


def test_builtin_pre_sales_and_after_sales_agents() -> None:
    pre = get_agent_type("pre_sales_agent")
    after = get_agent_type("after_sales_agent")
    assert pre is not None
    assert after is not None
    assert "rag.search" in pre.capability_ids
    assert "im.notify" in after.capability_ids
    assert pre.required_slots
    assert after.required_slots


def test_agent_type_for_intent_maps_eight_classes() -> None:
    assert agent_type_for_intent("pre_sales") is not None
    assert agent_type_for_intent("after_sales") is not None
    assert agent_type_for_intent("content_creation") is not None
    assert agent_type_for_intent("greeting") is None
    assert agent_type_for_intent("conversation") is None


def test_registry_lists_business_types() -> None:
    ids = {t.type_id for t in list_agent_types()}
    assert "pre_sales_agent" in ids
    assert "after_sales_agent" in ids
    assert "content_agent" in ids
