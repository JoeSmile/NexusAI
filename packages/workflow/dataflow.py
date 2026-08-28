"""Workflow dataflow — edges, ${output}/${input} refs, ready-set (Task 40.80 / R-C)."""

from __future__ import annotations

import re
from typing import Any

from packages.workflow.ir import WorkflowEdge, WorkflowIR, WorkflowNode

_OUTPUT_REF = re.compile(r"^\$\{output\.([A-Za-z0-9_-]+)\.([^}]+)\}$")
_INPUT_REF = re.compile(r"^\$\{input\.([A-Za-z0-9_.-]+)\}$")
_ANY_OUTPUT = re.compile(r"\$\{output\.")
_ANY_INPUT = re.compile(r"\$\{input\.")


class DataflowError(ValueError):
    """Raised for static or runtime dataflow failures (map to node failed)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def parse_output_ref(value: str) -> tuple[str, str] | None:
    m = _OUTPUT_REF.match(value.strip()) if isinstance(value, str) else None
    return (m.group(1), m.group(2)) if m else None


def parse_input_ref(value: str) -> str | None:
    m = _INPUT_REF.match(value.strip()) if isinstance(value, str) else None
    return m.group(1) if m else None


def get_dotted(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if cur is None:
            raise DataflowError("REF_MISSING", f"missing path segment before {part}")
        if isinstance(cur, dict):
            if part not in cur:
                raise DataflowError("REF_MISSING", f"missing field {path}")
            cur = cur[part]
        else:
            raise DataflowError("REF_MISSING", f"cannot traverse {path}")
    return cur


def detect_edge_cycles(node_ids: set[str], edges: list[WorkflowEdge]) -> None:
    """Raise IR_CYCLE if directed edge graph has a cycle."""
    adj: dict[str, list[str]] = {n: [] for n in node_ids}
    for e in edges:
        if e.from_node_id not in node_ids or e.to_node_id not in node_ids:
            raise DataflowError(
                "IR_EDGE",
                f"edge references unknown node {e.from_node_id}->{e.to_node_id}",
            )
        adj[e.from_node_id].append(e.to_node_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in node_ids}

    def dfs(u: str) -> None:
        color[u] = GRAY
        for v in adj[u]:
            if color[v] == GRAY:
                raise DataflowError("IR_CYCLE", f"cycle involving {u}->{v}")
            if color[v] == WHITE:
                dfs(v)
        color[u] = BLACK

    for n in node_ids:
        if color[n] == WHITE:
            dfs(n)


def validate_edges_static(ir: WorkflowIR) -> None:
    """Save-time: node refs, cycles, no dual-bind (edge + inline ref same to_param)."""
    ids = {n.node_id for n in ir.nodes}
    detect_edge_cycles(ids, list(ir.edges or []))

    # edge to_param uniqueness per target
    bound: dict[tuple[str, str], str] = {}
    for e in ir.edges or []:
        key = (e.to_node_id, e.to_param)
        if key in bound:
            raise DataflowError(
                "IR_EDGE",
                f"duplicate edge bind {e.to_node_id}.{e.to_param}",
            )
        bound[key] = e.from_node_id

    for node in ir.nodes:
        for pname, pval in (node.params or {}).items():
            if not isinstance(pval, str):
                continue
            if parse_output_ref(pval):
                key = (node.node_id, pname)
                if key in bound:
                    raise DataflowError(
                        "IR_EDGE",
                        f"dual bind edge+inline ref on {node.node_id}.{pname}",
                    )
                src, _field = parse_output_ref(pval)  # type: ignore[misc]
                if src not in ids:
                    raise DataflowError(
                        "IR_EDGE",
                        f"output ref unknown node {src} in {node.node_id}.{pname}",
                    )
            elif _ANY_OUTPUT.search(pval):
                raise DataflowError(
                    "IR_EDGE",
                    f"malformed output ref in {node.node_id}.{pname}",
                )
            if parse_input_ref(pval):
                name = parse_input_ref(pval)
                if ir.inputs and name not in ir.inputs:
                    raise DataflowError(
                        "IR_EDGE",
                        f"unknown input.{name} in {node.node_id}.{pname}",
                    )


def predecessors(ir: WorkflowIR, node_id: str) -> set[str]:
    return {e.from_node_id for e in (ir.edges or []) if e.to_node_id == node_id}


def ready_node_ids(
    ir: WorkflowIR,
    statuses: dict[str, str],
) -> list[str]:
    """
    Nodes that are pending and every predecessor is succeeded or skipped.
    Empty edges → all pending are ready (caller should take IR order serially).
    """
    ready: list[str] = []
    for node in ir.nodes:
        st = statuses.get(node.node_id, "pending")
        if st != "pending":
            continue
        preds = predecessors(ir, node.node_id)
        if all(statuses.get(p) in ("succeeded", "skipped") for p in preds):
            ready.append(node.node_id)
    return ready


def apply_edge_bindings(
    ir: WorkflowIR,
    node_id: str,
    params: dict[str, Any],
    *,
    outputs: dict[str, Any],
) -> dict[str, Any]:
    """Merge edge-driven to_param values into params (edges win over missing keys)."""
    out = dict(params)
    for e in ir.edges or []:
        if e.to_node_id != node_id:
            continue
        src = outputs.get(e.from_node_id)
        if src is None:
            raise DataflowError(
                "REF_MISSING",
                f"no output from {e.from_node_id} for {node_id}.{e.to_param}",
            )
        field = e.from_field or "result"
        out[e.to_param] = get_dotted(src, field)
    return out


def resolve_param_value(
    value: Any,
    *,
    outputs: dict[str, Any],
    inputs: dict[str, Any],
) -> Any:
    if not isinstance(value, str):
        return value
    oref = parse_output_ref(value)
    if oref:
        nid, path = oref
        src = outputs.get(nid)
        if src is None:
            raise DataflowError("REF_MISSING", f"no output from {nid}")
        return get_dotted(src, path)
    iref = parse_input_ref(value)
    if iref:
        if iref not in inputs:
            raise DataflowError("REF_MISSING", f"missing input.{iref}")
        return inputs[iref]
    if _ANY_OUTPUT.search(value) or _ANY_INPUT.search(value):
        raise DataflowError("REF_MISSING", f"malformed ref: {value}")
    return value


def resolve_params(
    params: dict[str, Any],
    *,
    outputs: dict[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    return {
        k: resolve_param_value(v, outputs=outputs, inputs=inputs)
        for k, v in params.items()
    }


def eval_run_if(expr: str | None, *, outputs: dict[str, Any], inputs: dict[str, Any]) -> bool:
    """V1: missing/empty → True; `${input.x}` / literal true/false; else truthy resolve.

    评审 08-14 I-3/Minor2:引用缺失(REF_MISSING)由 resolve 抛 DataflowError → 节点
    failed(与 F4 对齐,不是跳过);解析出的字符串 "false"/"0" 按字面量判定,不 bool(str)。
    """
    if expr is None or str(expr).strip() == "":
        return True
    s = str(expr).strip()
    if s.lower() in ("true", "1", "yes"):
        return True
    if s.lower() in ("false", "0", "no"):
        return False
    val = resolve_param_value(s, outputs=outputs, inputs=inputs)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "1", "yes"):
            return True
        if v in ("false", "0", "no"):
            return False
    return bool(val)


def node_order_index(ir: WorkflowIR) -> dict[str, int]:
    return {n.node_id: i for i, n in enumerate(ir.nodes)}


def pick_next_ready(ir: WorkflowIR, statuses: dict[str, str]) -> WorkflowNode | None:
    ready = ready_node_ids(ir, statuses)
    if not ready:
        return None
    order = node_order_index(ir)
    ready.sort(key=lambda nid: order.get(nid, 10**9))
    nid = ready[0]
    for n in ir.nodes:
        if n.node_id == nid:
            return n
    return None
