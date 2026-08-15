"""Wave C1 — Workflow IR model tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.workflow.ir import (
    WorkflowIR,
    WorkflowNode,
    validate_ir_capabilities,
    validate_params_against_spec,
)


def test_ir_empty_nodes_ok() -> None:
    ir = WorkflowIR(nodes=[])
    assert ir.ir_schema == "1"
    assert ir.edges == []


def test_ir_accepts_nonempty_edges() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(node_id="n1", capability_id="rag-ask"),
            WorkflowNode(node_id="n2", capability_id="rag-ask"),
        ],
        edges=[
            {
                "from_node_id": "n1",
                "from_field": "result",
                "to_node_id": "n2",
                "to_param": "query",
            }
        ],
    )
    assert len(ir.edges) == 1
    assert ir.edges[0].from_node_id == "n1"


def test_ir_rejects_duplicate_node_id() -> None:
    with pytest.raises(ValidationError):
        WorkflowIR(
            nodes=[
                WorkflowNode(node_id="n1", capability_id="rag-ask"),
                WorkflowNode(node_id="n1", capability_id="nexusai-chat"),
            ]
        )


def test_node_rejects_forbidden_param_keys() -> None:
    with pytest.raises(ValidationError):
        WorkflowNode(
            node_id="n1",
            capability_id="rag-ask",
            params={"api_key": "sk-x", "query": "hi"},
        )


def test_params_empty_when_no_spec() -> None:
    validate_params_against_spec({}, None)
    with pytest.raises(ValueError, match="must be empty"):
        validate_params_against_spec({"x": 1}, None)


def test_params_required_and_types() -> None:
    spec = {
        "query": {"type": "string", "required": True},
        "search_k": {"type": "number", "required": False, "default": 3},
        "flag": {"type": "boolean", "required": False},
        "mode": {"type": "enum", "required": True, "enum_values": ["a", "b"]},
    }
    validate_params_against_spec(
        {"query": "hello", "search_k": 5, "flag": True, "mode": "a"},
        spec,
    )
    with pytest.raises(ValueError, match="missing required"):
        validate_params_against_spec({"mode": "a"}, spec)
    with pytest.raises(ValueError, match="unknown"):
        validate_params_against_spec(
            {"query": "h", "mode": "a", "extra": 1},
            spec,
        )
    with pytest.raises(ValueError, match="number"):
        validate_params_against_spec(
            {"query": "h", "mode": "a", "search_k": "3"},
            spec,
        )
    with pytest.raises(ValueError, match="one of"):
        validate_params_against_spec({"query": "h", "mode": "z"}, spec)


def test_validate_ir_capabilities() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(
                node_id="n1",
                capability_id="rag-ask",
                params={"query": "q"},
            )
        ]
    )
    registry = {
        "rag-ask": {"query": {"type": "string", "required": True}},
    }

    validate_ir_capabilities(
        ir,
        get_param_spec=lambda cid: registry.get(cid),
        capability_exists=lambda cid: cid in registry,
    )

    with pytest.raises(ValueError, match="unknown capability"):
        validate_ir_capabilities(
            ir,
            get_param_spec=lambda _cid: None,
            capability_exists=lambda _cid: False,
        )
