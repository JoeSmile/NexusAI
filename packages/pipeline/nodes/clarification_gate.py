"""Clarification gate — hold pipeline when triggers fire (Task 65 slice 6)."""

from __future__ import annotations

from packages.observability.decorators import enrich_span, observe
from packages.pipeline.state import PipelineState
from packages.plan.clarification import (
    ABANDON_AFTER,
    abandon_clarification,
    evaluate_clarification_triggers,
    get_clarification_attempts,
    get_pending,
    hold_for_clarification,
    persist_clarification_attempts,
    set_clarification_attempts,
    try_resolve_pending,
)


@observe(name="pipeline.clarification_gate")
async def clarification_gate(state: PipelineState) -> PipelineState:
    state.setdefault("pending_clarification", False)  # type: ignore[typeddict-item]
    state.setdefault("clarification", None)  # type: ignore[typeddict-item]
    state.setdefault("clarification_resolved", False)  # type: ignore[typeddict-item]

    await get_pending(state, audit_on_timeout=True)

    if await try_resolve_pending(state):
        payload = evaluate_clarification_triggers(state)
        if payload is None:
            enrich_span(metadata={"clarification": "resolved"})
            return state
        n = set_clarification_attempts(state, get_clarification_attempts(state) + 1)
        await persist_clarification_attempts(state)
        if n >= ABANDON_AFTER:
            await abandon_clarification(state, reason="rehold")
            enrich_span(metadata={"clarification": "abandoned", "reason": "rehold"})
            return state
        await hold_for_clarification(state, payload)
        enrich_span(metadata={"clarification": "rehold", "source": payload.source, "attempts": n})
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

    await hold_for_clarification(state, payload)
    enrich_span(metadata={"clarification": "hold", "source": payload.source})
    return state


def route_after_clarification(state: PipelineState) -> str:
    if state.get("pending_clarification"):
        return "hold"
    return "continue"
