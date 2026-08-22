"""Plan 执行事件总线 + 图快照（Task 56 切片 4 · F5）。"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_EVENTS = 2048


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PlanGraphEvent:
    seq: int
    ts: str
    type: str
    payload: dict[str, Any]


@dataclass
class PlanGraphNode:
    id: str
    capability_id: str = ""
    status: str = "pending"
    label: str = ""
    summary: str = ""


@dataclass
class PlanGraphEdge:
    source: str
    target: str


@dataclass
class PlanGraphSnapshot:
    trace_id: str
    goal: str = ""
    nodes: list[PlanGraphNode] = field(default_factory=list)
    edges: list[PlanGraphEdge] = field(default_factory=list)
    latest_seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "goal": self.goal,
            "nodes": [
                {
                    "id": n.id,
                    "capability_id": n.capability_id,
                    "status": n.status,
                    "label": n.label,
                    "summary": n.summary,
                }
                for n in self.nodes
            ],
            "edges": [{"source": e.source, "target": e.target} for e in self.edges],
            "latest_seq": self.latest_seq,
        }


class PlanEventBus:
    """线程安全事件总线 + 持续图快照。"""

    def __init__(self, trace_id: str, *, max_events: int = MAX_EVENTS) -> None:
        self.trace_id = trace_id
        self._max_events = max(64, int(max_events))
        self._events: deque[PlanGraphEvent] = deque(maxlen=self._max_events)
        self._nodes: dict[str, PlanGraphNode] = {}
        self._edges: set[tuple[str, str]] = set()
        self._goal = ""
        self._seq = 0
        self._lock = threading.Lock()

    def emit(self, event_type: str, payload: dict[str, Any]) -> PlanGraphEvent:
        with self._lock:
            self._seq += 1
            event = PlanGraphEvent(
                seq=self._seq,
                ts=_utc_now_iso(),
                type=event_type,
                payload=dict(payload),
            )
            self._events.append(event)
            return event

    def set_goal(self, goal: str) -> None:
        with self._lock:
            self._goal = (goal or "")[:2000]

    def upsert_node(
        self,
        node_id: str,
        *,
        capability_id: str = "",
        status: str | None = None,
        label: str = "",
        summary: str = "",
    ) -> None:
        with self._lock:
            prev = self._nodes.get(node_id)
            self._nodes[node_id] = PlanGraphNode(
                id=node_id,
                capability_id=capability_id or (prev.capability_id if prev else ""),
                status=status or (prev.status if prev else "pending"),
                label=label or (prev.label if prev else node_id),
                summary=summary or (prev.summary if prev else ""),
            )

    def add_edge(self, source: str, target: str) -> None:
        with self._lock:
            self._edges.add((source, target))

    def publish_plan(self, *, goal: str, steps: list[dict[str, Any]]) -> PlanGraphEvent:
        self.set_goal(goal)
        overview: list[dict[str, str]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            sid = str(step.get("id") or "")
            cap = str(step.get("capability_id") or "")
            if not sid:
                continue
            self.upsert_node(sid, capability_id=cap, status="pending", label=sid)
            overview.append({"id": sid, "capability_id": cap})
            for dep in step.get("depends_on") or []:
                dep_s = str(dep)
                if dep_s:
                    self.add_edge(dep_s, sid)
        return self.emit(
            "plan",
            {
                "goal": goal,
                "steps": overview,
            },
        )

    def publish_step(
        self,
        step_id: str,
        *,
        capability_id: str = "",
        status: str,
        summary: str = "",
    ) -> PlanGraphEvent:
        self.upsert_node(
            step_id,
            capability_id=capability_id,
            status=status,
            summary=summary[:500],
        )
        if status == "running":
            self.emit(
                "tool_call",
                {
                    "step_id": step_id,
                    "capability_id": capability_id,
                    "label": capability_id or step_id,
                },
            )
        elif status in ("succeeded", "failed", "skipped"):
            self.emit(
                "tool_result",
                {
                    "step_id": step_id,
                    "capability_id": capability_id,
                    "status": status,
                    "summary": summary[:500],
                },
            )
        return self.emit(
            "step",
            {
                "id": step_id,
                "capability_id": capability_id,
                "status": status,
                "summary": summary[:500],
            },
        )

    def publish_retry(self, step_id: str, *, attempt: int, max_attempts: int) -> PlanGraphEvent:
        return self.emit(
            "retry",
            {"step_id": step_id, "attempt": attempt, "max_attempts": max_attempts},
        )

    def publish_replan(
        self,
        *,
        reason: str,
        new_steps: list[dict[str, str]],
        detail: str | None = None,
    ) -> PlanGraphEvent:
        payload: dict[str, Any] = {
            "reason": reason[:500],
            "new_steps": new_steps,
        }
        if detail:
            payload["detail"] = detail[:500]
        return self.emit("replan", payload)

    def events_since(self, seq: int = 0) -> list[PlanGraphEvent]:
        with self._lock:
            return [e for e in self._events if e.seq > seq]

    def events_all(self) -> list[PlanGraphEvent]:
        with self._lock:
            return list(self._events)

    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    def snapshot(self) -> PlanGraphSnapshot:
        with self._lock:
            nodes = sorted(self._nodes.values(), key=lambda n: n.id)
            edges = sorted(
                (PlanGraphEdge(source=s, target=t) for s, t in self._edges),
                key=lambda e: (e.source, e.target),
            )
            return PlanGraphSnapshot(
                trace_id=self.trace_id,
                goal=self._goal,
                nodes=nodes,
                edges=edges,
                latest_seq=self._seq,
            )

    def snapshot_dict(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            **snap.to_dict(),
            "events": [event_to_dict(e) for e in self.events_all()],
        }


def event_to_dict(event: PlanGraphEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "ts": event.ts,
        "type": event.type,
        "payload": event.payload,
    }


def event_to_sse_payload(event: PlanGraphEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "seq": event.seq,
        "ts": event.ts,
        **event.payload,
    }


_REGISTRY_LOCK = threading.Lock()
_RUN_BUSES: dict[str, PlanEventBus] = {}


def get_run_bus(trace_id: str) -> PlanEventBus:
    tid = (trace_id or "").strip()
    if not tid:
        raise ValueError("trace_id required")
    with _REGISTRY_LOCK:
        bus = _RUN_BUSES.get(tid)
        if bus is None:
            bus = PlanEventBus(tid)
            _RUN_BUSES[tid] = bus
        return bus


def get_run_bus_optional(trace_id: str | None) -> PlanEventBus | None:
    tid = (trace_id or "").strip()
    if not tid:
        return None
    with _REGISTRY_LOCK:
        return _RUN_BUSES.get(tid)


def bus_for_state(state: dict[str, Any] | None) -> PlanEventBus | None:
    if not isinstance(state, dict):
        return None
    tid = str(state.get("trace_id") or "").strip()
    if not tid:
        return None
    return get_run_bus(tid)


def release_run_bus(trace_id: str) -> None:
    tid = (trace_id or "").strip()
    if not tid:
        return
    with _REGISTRY_LOCK:
        _RUN_BUSES.pop(tid, None)
