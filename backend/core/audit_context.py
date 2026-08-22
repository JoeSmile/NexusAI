"""审计血缘上下文（Task 56 切片 5）— 跨节点/invoke 传递 trace 链。"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class AuditLineage:
    trace_id: str | None = None
    parent_trace_id: str | None = None
    tool_use_id: str | None = None
    run_id: str | None = None
    node_id: str | None = None


_lineage: ContextVar[AuditLineage | None] = ContextVar("audit_lineage", default=None)


def bind_audit_lineage(
    *,
    trace_id: str | None = None,
    parent_trace_id: str | None = None,
    tool_use_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
) -> AuditLineage:
    current = get_audit_lineage()
    merged = AuditLineage(
        trace_id=trace_id or current.trace_id,
        parent_trace_id=parent_trace_id if parent_trace_id is not None else current.parent_trace_id,
        tool_use_id=tool_use_id or current.tool_use_id,
        run_id=run_id or current.run_id,
        node_id=node_id or current.node_id,
    )
    _lineage.set(merged)
    return merged


def get_audit_lineage() -> AuditLineage:
    return _lineage.get() or AuditLineage()


def clear_audit_lineage() -> None:
    _lineage.set(None)
