"""Task 40.81 — nested runs / waiting_child / forged parent (unit-level)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from packages.workflow import runner as run_svc
from packages.workflow.composition import MAX_COMPOSITION_DEPTH
from packages.workflow.ir import WorkflowIR, WorkflowNode
from packages.workflow.run_state import can_node_transition


def test_waiting_child_transitions() -> None:
    assert can_node_transition("pending", "waiting_child")
    assert can_node_transition("running", "waiting_child")
    assert can_node_transition("waiting_child", "succeeded")
    assert can_node_transition("waiting_child", "failed")
    assert not can_node_transition("waiting_child", "waiting")


def test_kind_workflow_ir_ok() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(node_id="leaf", capability_id="rag-ask"),
            WorkflowNode(node_id="sub", kind="workflow", workflow_id="wf-child"),
        ]
    )
    assert ir.nodes[1].kind == "workflow"


def test_start_run_forged_parent_rejected(monkeypatch) -> None:
    class FakeSession:
        pass

    class FakeTenant:
        tenant_id = "t1"
        user_id = "u1"
        role = "user"
        is_cross_tenant = False
        credential_kind = "user"

    class FakeScope:
        primary_org_unit_id = "ou1"

    with pytest.raises(HTTPException) as ei:
        run_svc.start_run(
            FakeSession(),  # type: ignore[arg-type]
            tenant=FakeTenant(),  # type: ignore[arg-type]
            org_scope=FakeScope(),  # type: ignore[arg-type]
            workflow_id="wf1",
            parent_run_id="parent-x",
            parent_node_id="n1",
            _internal_nested=False,
        )
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "PARENT_FORGED"


def test_max_composition_depth_constant() -> None:
    # 真源在 composition.py(runner 不再转发,评审 08-14 Minor1)
    assert MAX_COMPOSITION_DEPTH == 3
