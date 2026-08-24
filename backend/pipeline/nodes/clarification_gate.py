"""Clarification gate — hold pipeline when triggers fire (Task 65 slice 6)."""

from __future__ import annotations

from backend.core.plan.clarification import (
    audit_clarification_event,
    evaluate_clarification_triggers,
    get_pending,
    store_pending,
    try_resolve_pending,
)
from backend.core.plan.event_bus import bus_for_state
from backend.observability.decorators import enrich_span, observe
from backend.pipeline.state import PipelineState


@observe(name="pipeline.clarification_gate")
async def clarification_gate(state: PipelineState) -> PipelineState:
    state.setdefault("pending_clarification", False)  # type: ignore[typeddict-item]
    state.setdefault("clarification", None)  # type: ignore[typeddict-item]
    state.setdefault("clarification_resolved", False)  # type: ignore[typeddict-item]

    await get_pending(state, audit_on_timeout=True)

    if await try_resolve_pending(state):
        enrich_span(metadata={"clarification": "resolved"})
        return state

    existing = await get_pending(state)
    if existing:
        state["pending_clarification"] = True  # type: ignore[typeddict-item]
        state["clarification"] = existing
        state["response"] = str(existing.get("question") or "")
        state["finish_reason"] = "clarification_pending"
        state["task_plan"] = None
        return state

    payload = evaluate_clarification_triggers(state)
    if payload is None:
        enrich_span(metadata={"clarification": "pass"})
        return state

    body = payload.to_dict()
    state["pending_clarification"] = True  # type: ignore[typeddict-item]
    state["clarification"] = body
    state["response"] = payload.question
    state["finish_reason"] = "clarification_pending"
    state["task_plan"] = None

    await store_pending(state, payload)
    audit_clarification_event(
        tenant_id=str(state.get("tenant_id") or ""),
        user_id=str(state.get("user_id") or ""),
        trace_id=payload.trace_id,
        event="triggered",
        payload=body,
    )

    bus = bus_for_state(state)
    if bus is not None:
        bus.emit(
            "clarify",
            {
                "source": payload.source,
                "question": payload.question,
                "options": payload.options,
                "trace_id": payload.trace_id,
            },
        )

    enrich_span(metadata={"clarification": "hold", "source": payload.source})
    return state


def route_after_clarification(state: PipelineState) -> str:
    if state.get("pending_clarification"):
        return "hold"
    return "continue"
