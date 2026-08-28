"""Task 40.80 — IR dataflow edges + ready-set + refs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.workflow.dataflow import (
    DataflowError,
    detect_edge_cycles,
    get_dotted,
    pick_next_ready,
    ready_node_ids,
    resolve_params,
    validate_edges_static,
)
from packages.workflow.ir import WorkflowEdge, WorkflowIR, WorkflowNode


def test_edge_four_field_model() -> None:
    e = WorkflowEdge(
        from_node_id="a",
        from_field="result",
        to_node_id="b",
        to_param="query",
    )
    assert e.from_field == "result"
    # default from_field
    e2 = WorkflowEdge(from_node_id="a", to_node_id="b", to_param="q")
    assert e2.from_field == "result"


def test_ir_accepts_edges_no_cycle() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(node_id="a", capability_id="rag-ask", params={"query": "x"}),
            WorkflowNode(node_id="b", capability_id="rag-ask", params={}),
        ],
        edges=[
            WorkflowEdge(
                from_node_id="a",
                from_field="result",
                to_node_id="b",
                to_param="query",
            )
        ],
    )
    assert len(ir.edges) == 1
    # dual bind: edge + inline same to_param → reject
    with pytest.raises(ValidationError):
        WorkflowIR(
            nodes=[
                WorkflowNode(node_id="a", capability_id="rag-ask"),
                WorkflowNode(
                    node_id="b",
                    capability_id="rag-ask",
                    params={"query": "${output.a.result}"},
                ),
            ],
            edges=[
                WorkflowEdge(
                    from_node_id="a",
                    to_node_id="b",
                    to_param="query",
                )
            ],
        )


def test_ir_rejects_cycle() -> None:
    with pytest.raises(ValidationError):
        WorkflowIR(
            nodes=[
                WorkflowNode(node_id="a", capability_id="rag-ask"),
                WorkflowNode(node_id="b", capability_id="rag-ask"),
            ],
            edges=[
                WorkflowEdge(from_node_id="a", to_node_id="b", to_param="x"),
                WorkflowEdge(from_node_id="b", to_node_id="a", to_param="y"),
            ],
        )


def test_kind_workflow_and_agent_allowed_in_ir() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(node_id="w", kind="workflow", workflow_id="wf-child"),
            WorkflowNode(node_id="ag", kind="agent", agent_id="vendor-risk"),
        ]
    )
    assert ir.nodes[0].workflow_id == "wf-child"
    with pytest.raises(ValidationError):
        WorkflowNode(node_id="bad", kind="capability", workflow_id="x")


def test_ready_set_empty_edges_is_ir_order() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(node_id="a", capability_id="rag-ask"),
            WorkflowNode(node_id="b", capability_id="rag-ask"),
        ]
    )
    st = {"a": "pending", "b": "pending"}
    assert ready_node_ids(ir, st) == ["a", "b"]
    assert pick_next_ready(ir, st).node_id == "a"
    st["a"] = "succeeded"
    assert pick_next_ready(ir, st).node_id == "b"


def test_ready_set_respects_edge_preds() -> None:
    ir = WorkflowIR(
        nodes=[
            WorkflowNode(node_id="a", capability_id="rag-ask"),
            WorkflowNode(node_id="b", capability_id="rag-ask"),
            WorkflowNode(node_id="c", capability_id="rag-ask"),
        ],
        edges=[
            WorkflowEdge(from_node_id="a", to_node_id="c", to_param="q"),
            WorkflowEdge(from_node_id="b", to_node_id="c", to_param="k"),
        ],
    )
    st = {"a": "pending", "b": "succeeded", "c": "pending"}
    # c waits for a; a and ... ready are a only (b done)
    assert pick_next_ready(ir, st).node_id == "a"
    st["a"] = "succeeded"
    assert pick_next_ready(ir, st).node_id == "c"


def test_resolve_output_and_input_refs() -> None:
    out = resolve_params(
        {
            "q": "${output.n1.result}",
            "topic": "${input.topic}",
            "lit": "hello",
        },
        outputs={"n1": {"result": "from-a", "evidence": []}},
        inputs={"topic": "热点"},
    )
    assert out == {"q": "from-a", "topic": "热点", "lit": "hello"}
    with pytest.raises(DataflowError) as ei:
        resolve_params(
            {"q": "${output.missing.result}"},
            outputs={},
            inputs={},
        )
    assert ei.value.code == "REF_MISSING"


def test_get_dotted() -> None:
    assert get_dotted({"a": {"b": 1}}, "a.b") == 1
    with pytest.raises(DataflowError):
        get_dotted({"a": 1}, "a.b")
