"""Task 40.82 — agent nodes in runner (same-run Hub chain)."""

from __future__ import annotations

import pytest

from packages.workflow.composition import (
    MAX_COMPOSITION_DEPTH,
    CompositionDepthExceeded,
    check_composition_budget,
)
from packages.workflow.ir import WorkflowIR, WorkflowNode


def test_agent_kind_in_ir() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(node_id="a", kind="agent", agent_id="vendor-risk"),
        ]
    )
    assert ir.nodes[0].agent_id == "vendor-risk"
    assert ir.nodes[0].capability_id is None


def test_composition_depth_budget_shared() -> None:
    check_composition_budget(2, 1)
    with pytest.raises(CompositionDepthExceeded):
        check_composition_budget(3, 1)
    assert MAX_COMPOSITION_DEPTH == 3
