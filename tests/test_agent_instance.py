"""Task 62 P1 — AgentInstance independent trace + lifecycle."""

from __future__ import annotations

import pytest

from backend.core.plan.agent_instance import (
    AgentInstanceStatus,
    complete_agent_instance,
    fail_agent_instance,
    mark_instance_running,
    spawn_agent_instance,
    spawn_trace_id,
)
from backend.core.plan.agent_spawn import (
    complete_agent_instance_for_step,
    fail_agent_instance_for_step,
    spawn_sub_agent_instance,
)
from backend.pipeline.state import make_initial_state


def test_spawn_trace_id_is_child_of_parent() -> None:
    parent = "tr_main_abc"
    child = spawn_trace_id(parent, "s1")
    retry = spawn_trace_id(parent, "s1", attempt=2)
    assert child.startswith(f"{parent}:spawn:")
    assert child != parent
    assert retry.endswith(":r2")
    assert retry != child


def test_spawn_agent_instance_fields() -> None:
    inst = spawn_agent_instance(
        agent_type_id="pre_sales_agent",
        parent_run_id="tr_parent",
        step_id="step_1",
        capability_id="rag.search",
        task="查产品",
    )
    assert inst.agent_type_id == "pre_sales_agent"
    assert inst.parent_run_id == "tr_parent"
    assert inst.trace_id.startswith("tr_parent:spawn:")
    assert inst.status == AgentInstanceStatus.SPAWNED


def test_lifecycle_complete_and_fail() -> None:
    inst = spawn_agent_instance(
        agent_type_id="pre_sales_agent",
        parent_run_id="tr_p",
        step_id="s1",
        capability_id="rag.search",
    )
    running = mark_instance_running(inst)
    assert running.status == AgentInstanceStatus.RUNNING
    done = complete_agent_instance(running, output_summary="ok")
    assert done.status == AgentInstanceStatus.COMPLETED
    assert done.completed_at is not None

    failed = fail_agent_instance(running, "boom")
    assert failed.status == AgentInstanceStatus.FAILED
    assert failed.error == "boom"


@pytest.fixture(autouse=True)
def _noop_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.core.plan.agent_instance.write_audit_sync",
        lambda *a, **k: True,
    )


def test_spawn_sub_agent_instance_records_on_state() -> None:
    state = make_initial_state("t1", "u1", "s1", "报价")
    state["trace_id"] = "tr_main"
    state["agent_type_id"] = "pre_sales_agent"
    state["slot_values"] = {"product_scope": "NexusAI"}
    inst = spawn_sub_agent_instance(
        state,
        step_id="s1",
        capability_id="rag.search",
        task="查报价",
        attempt=2,
        max_attempts=3,
    )
    assert inst is not None
    assert inst.attempt == 2
    assert inst.max_attempts == 3
    assert inst.trace_id.endswith(":r2")
    assert inst is not None
    assert inst.trace_id != state["trace_id"]
    rows = state.get("agent_instances") or []
    assert len(rows) == 1
    assert rows[0]["instance_id"] == inst.instance_id
    assert rows[0]["status"] == AgentInstanceStatus.RUNNING


def test_complete_and_fail_update_state() -> None:
    state = make_initial_state("t1", "u1", "s1", "报价")
    state["trace_id"] = "tr_main"
    state["agent_type_id"] = "pre_sales_agent"
    inst = spawn_sub_agent_instance(
        state,
        step_id="s1",
        capability_id="rag.search",
    )
    assert inst is not None
    complete_agent_instance_for_step(state, inst, {"output": "done"})
    assert state["agent_instances"][0]["status"] == AgentInstanceStatus.COMPLETED

    inst2 = spawn_sub_agent_instance(
        state,
        step_id="s2",
        capability_id="rag.search",
    )
    assert inst2 is not None
    fail_agent_instance_for_step(state, inst2, "err")
    assert state["agent_instances"][-1]["status"] == AgentInstanceStatus.FAILED
