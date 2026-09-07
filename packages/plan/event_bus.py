"""Plan 执行事件总线 + 图快照（Task 56 切片 4 · F5）。"""

from __future__ import annotations

import asyncio
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
        # Task 94: 有界队列淘汰断点（被挤掉的最大 seq；0=未淘汰过）
        self._dropped_upto: int = 0
        # Task 94: asyncio 等待者（wait_next）。emit 与 wait_next 均在事件循环内调用；
        # 若未来 emit 来自其他线程，需改 loop.call_soon_threadsafe。
        self._waiters: set[asyncio.Event] = set()

    def emit(self, event_type: str, payload: dict[str, Any]) -> PlanGraphEvent:
        with self._lock:
            if len(self._events) == self._max_events:
                # 本次 append 将挤掉最老事件，记录其 seq 作为补发 gap 断点
                self._dropped_upto = self._events[0].seq
            self._seq += 1
            event = PlanGraphEvent(
                seq=self._seq,
                ts=_utc_now_iso(),
                type=event_type,
                payload=dict(payload),
            )
            self._events.append(event)
        self._notify_waiters()
        return event

    def dropped_upto(self) -> int:
        """已被有界队列淘汰的最大事件 seq；0 = 无淘汰。

        订阅方补发时若 last_seq < dropped_upto()，说明存在空洞，
        必须降级（如回拉终态文本），不能静默拼出残缺序列。
        """
        with self._lock:
            return self._dropped_upto

    def _notify_waiters(self) -> None:
        for waiter in list(self._waiters):
            if not waiter.is_set():
                waiter.set()

    async def wait_next(
        self, last_seq: int, *, timeout: float | None = None
    ) -> list[PlanGraphEvent]:
        """等待并返回 seq > last_seq 的新事件；超时返回 []。

        若 last_seq 已被有界队列淘汰（存在空洞）则抛 BusGapError——
        调用方应降级（快照/终态文本），不得静默续拼。
        """
        while True:
            # gap 判定必须先于 events_since：deque 淘汰总是从最老开始，
            # 剩余序列本身连续，但 last_seq 之后被淘汰的部分对订阅方就是洞
            if self.dropped_upto() > last_seq:
                raise BusGapError(
                    f"event gap: last_seq={last_seq} dropped_upto={self.dropped_upto()}"
                )
            events = self.events_since(last_seq)
            if events:
                return events
            waiter = asyncio.Event()
            self._waiters.add(waiter)
            try:
                # 注册后再查一次：消灭「注册前已 emit」的漏事件窗口
                if self.dropped_upto() > last_seq:
                    raise BusGapError(
                        f"event gap: last_seq={last_seq} dropped_upto={self.dropped_upto()}"
                    )
                events = self.events_since(last_seq)
                if events:
                    return events
                if timeout is None:
                    await waiter.wait()
                else:
                    try:
                        await asyncio.wait_for(waiter.wait(), timeout=timeout)
                    except TimeoutError:
                        return []
            finally:
                self._waiters.discard(waiter)

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

    def publish_plan(
        self,
        *,
        goal: str,
        steps: list[dict[str, Any]],
        coref_table: dict[str, Any] | None = None,
    ) -> PlanGraphEvent:
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
        payload: dict[str, Any] = {
            "goal": goal,
            "steps": overview,
        }
        if coref_table:
            payload["coref_table"] = coref_table
        return self.emit("plan", payload)

    def publish_task_plan_pending(self, *, message: str = "") -> PlanGraphEvent:
        """Task 70: 流式首帧占位 — 规划进行中。"""
        return self.emit(
            "task_plan_pending",
            {
                "status": "pending",
                "message": (message or "正在规划…")[:200],
            },
        )

    def publish_task_plan_done(
        self,
        *,
        ok: bool,
        goal: str = "",
        reason: str = "",
    ) -> PlanGraphEvent:
        """Task 70: 规划完成或失败（不含超时，超时见 publish_task_plan_timeout）。"""
        payload: dict[str, Any] = {"ok": ok, "status": "done" if ok else "failed"}
        if goal:
            payload["goal"] = goal[:2000]
        if reason:
            payload["reason"] = reason[:500]
        return self.emit("task_plan_done", payload)

    def publish_task_plan_timeout(self, *, timeout_s: float) -> PlanGraphEvent:
        """Task 70: 规划超时 → 降级直答。"""
        return self.emit(
            "task_plan_done",
            {
                "ok": False,
                "status": "timeout",
                "timeout_s": timeout_s,
                "reason": "plan_timeout_degrade_to_llm",
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


class BusGapError(Exception):
    """事件序列存在空洞（有界队列淘汰），补发不完整，需调用方降级。"""
