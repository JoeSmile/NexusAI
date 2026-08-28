"""Task 62 — orchestrator AgentType spawn wiring."""

from __future__ import annotations

import pytest

from packages.auth.models import TenantContext
from packages.auth.subagent import is_sub_agent
from backend.core.plan.agent_spawn import (
    SpawnBlockedError,
    boost_capabilities_for_agent_type,
    prepare_orchestrator_spawn,
    resolve_step_tenant,
)
from backend.core.plan.blackboard import Blackboard
from backend.pipeline.state import make_initial_state


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.core.plan.blackboard.write_audit_sync",
        lambda *a, **k: True,
    )


def test_boost_capabilities_prefers_agent_type_whitelist() -> None:
    caps = [
        {"id": "mail.draft", "name": "mail"},
        {"id": "rag.search", "name": "rag"},
        {"id": "web.search", "name": "web"},
    ]
    boosted = boost_capabilities_for_agent_type(caps, "pre_sales_agent")
    assert boosted[0]["id"] == "rag.search"


def test_resolve_step_tenant_uses_sub_agent_for_whitelisted_cap() -> None:
    state = make_initial_state("t1", "u1", "s1", "报价")
    state["agent_type_id"] = "pre_sales_agent"
    parent = TenantContext("t1", "u1", "user", ["chat:write"], False)
    child = resolve_step_tenant(
        state,
        step_capability_id="rag.search",
        parent=parent,
        step_id="s1",
    )
    assert is_sub_agent(child)
    assert child.parent_agent_id == "pre_sales_agent"


def test_resolve_step_tenant_keeps_main_for_non_whitelist() -> None:
    state = make_initial_state("t1", "u1", "s1", "报价")
    state["agent_type_id"] = "pre_sales_agent"
    parent = TenantContext("t1", "u1", "user", ["chat:write"], False)
    same = resolve_step_tenant(
        state,
        step_capability_id="web.search",
        parent=parent,
        step_id="s1",
    )
    assert not is_sub_agent(same)


def test_prepare_orchestrator_spawn_blocks_missing_slots() -> None:
    state = make_initial_state("t1", "u1", "s1", "介绍一下产品")
    state["agent_type_id"] = "pre_sales_agent"
    state["slot_values"] = {}
    bb = Blackboard()
    with pytest.raises(SpawnBlockedError) as exc:
        prepare_orchestrator_spawn(state, bb)
    assert exc.value.payload is not None
    assert exc.value.payload.source == "required_slots"
    topics = {e["topic"] for e in bb.list_entries()}
    assert "slots.missing" in topics


def test_prepare_orchestrator_spawn_writes_slots_filled() -> None:
    state = make_initial_state("t1", "u1", "s1", "介绍一下产品")
    state["agent_type_id"] = "pre_sales_agent"
    state["slot_values"] = {"product_scope": "NexusAI 中台"}
    bb = Blackboard()
    prepare_orchestrator_spawn(state, bb)
    topics = {e["topic"] for e in bb.list_entries()}
    assert "slots.filled" in topics


@pytest.mark.asyncio
async def test_orchestrator_spawn_blocked_holds_clarification(monkeypatch):
    from backend.core.plan.agent_spawn import SpawnBlockedError
    from backend.core.plan.clarification import get_pending
    from backend.core.plan.slot_gate import evaluate_required_slots
    from backend.pipeline.nodes.orchestrator import (
        orchestrator,
        route_after_orchestrator,
    )

    monkeypatch.setattr(
        "backend.core.plan.clarification.write_audit_sync",
        lambda *a, **k: True,
    )
    async def _write(self, tier, *, user_id, **payload):
        return {"tier": tier, "key": payload.get("key")}

    monkeypatch.setattr(
        "backend.core.memory_service.UnifiedMemoryService.write",
        _write,
    )
    monkeypatch.setenv("ORCHESTRATOR_ENABLED", "true")

    state = make_initial_state("t1", "u1", "s1", "介绍一下产品")
    state["agent_type_id"] = "pre_sales_agent"
    state["slot_values"] = {}
    state["clarification_resolved"] = True
    state["task_plan"] = {
        "goal": "test",
        "version": 1,
        "steps": [
            {
                "id": "s1",
                "capability_id": "rag.search",
                "params": {},
                "on_fail": "fail",
            }
        ],
    }

    payload = evaluate_required_slots(state)
    assert payload is not None

    async def _boom(*args, **kwargs):
        raise SpawnBlockedError(payload.question, payload=payload)

    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator.execute_plan_ir",
        _boom,
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.orchestrator._caps_index",
        lambda s: {"rag.search": {"spec": {}}},
    )

    out = await orchestrator(state)
    assert out["finish_reason"] == "clarification_pending"
    assert out["pending_clarification"] is True
    assert out.get("task_plan") is None
    assert route_after_orchestrator(out) == "write_memory"
    assert await get_pending(out) is not None
