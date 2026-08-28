"""AgentType spawn — sub-agent tenant + capability whitelist (Task 62 extension)."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from packages.auth.models import TenantContext
from packages.auth.subagent import is_sub_agent, make_sub_agent_context

from .agent_instance import (
    AgentInstance,
    audit_instance_event,
    complete_agent_instance,
    fail_agent_instance,
    mark_instance_running,
    record_instance_on_state,
    spawn_agent_instance,
)
from .agent_type import TOPIC_SLOTS_FILLED, AgentType, get_agent_type
from .clarification import ClarificationPayload
from .slot_gate import (
    evaluate_required_slots,
    missing_required_slots,
    slot_values_from_state,
    write_slots_missing_entry,
)


class SpawnBlockedError(Exception):
    """Required slots missing or capability not allowed for AgentType."""

    def __init__(
        self,
        message: str,
        *,
        payload: ClarificationPayload | None = None,
    ) -> None:
        super().__init__(message)
        self.payload = payload


def capability_allowed(agent_type: AgentType, capability_id: str) -> bool:
    allowed = agent_type.capability_ids
    if not allowed:
        return False
    return capability_id in allowed


def boost_capabilities_for_agent_type(
    caps: list[dict[str, Any]],
    agent_type_id: str | None,
) -> list[dict[str, Any]]:
    """Prefer AgentType whitelist capabilities in task_plan catalog ordering."""
    if not agent_type_id:
        return caps
    agent_type = get_agent_type(agent_type_id)
    if agent_type is None or not agent_type.capability_ids:
        return caps
    allow = set(agent_type.capability_ids)
    preferred = [c for c in caps if c.get("id") in allow]
    rest = [c for c in caps if c.get("id") not in allow]
    return preferred + rest


def spawn_sub_agent_instance(
    state: dict[str, Any],
    *,
    step_id: str,
    capability_id: str,
    task: str = "",
    attempt: int = 1,
    max_attempts: int = 1,
    model_name: str | None = None,
    escalated_model: str | None = None,
) -> AgentInstance | None:
    """Create AgentInstance when orchestrator step uses sub-agent context."""
    type_id = str(state.get("agent_type_id") or "").strip()
    if not type_id:
        return None
    agent_type = get_agent_type(type_id)
    if agent_type is None or not capability_allowed(agent_type, capability_id):
        return None
    parent_run_id = str(state.get("trace_id") or "")
    tenant_id = str(state.get("tenant_id") or "")
    user_id = str(state.get("user_id") or "")
    instance = spawn_agent_instance(
        agent_type_id=type_id,
        parent_run_id=parent_run_id,
        step_id=step_id,
        capability_id=capability_id,
        task=task,
        attempt=attempt,
        max_attempts=max_attempts,
        model_name=model_name,
        escalated_model=escalated_model,
    )
    audit_instance_event(
        event="spawned",
        instance=instance,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    instance = mark_instance_running(instance)
    audit_instance_event(
        event="running",
        instance=instance,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    record_instance_on_state(state, instance)
    spawn_n = int(state.get("orchestrator_spawn_total") or 0) + 1
    state["orchestrator_spawn_total"] = spawn_n
    return instance


def complete_agent_instance_for_step(
    state: dict[str, Any],
    instance: AgentInstance,
    outcome: dict[str, Any],
) -> AgentInstance:
    summary = str(outcome.get("output") or outcome.get("text") or "")
    updated = complete_agent_instance(instance, output_summary=summary)
    audit_instance_event(
        event="completed",
        instance=updated,
        tenant_id=str(state.get("tenant_id") or ""),
        user_id=str(state.get("user_id") or ""),
        extra={"output_summary": summary[:500]},
    )
    record_instance_on_state(state, updated)
    return updated


def fail_agent_instance_for_step(
    state: dict[str, Any],
    instance: AgentInstance,
    error: str,
) -> AgentInstance:
    updated = fail_agent_instance(instance, error)
    audit_instance_event(
        event="failed",
        instance=updated,
        tenant_id=str(state.get("tenant_id") or ""),
        user_id=str(state.get("user_id") or ""),
        extra={"error": error[:500]},
    )
    record_instance_on_state(state, updated)
    return updated


def resolve_step_tenant(
    state: dict[str, Any],
    *,
    step_capability_id: str,
    parent: TenantContext,
    step_id: str = "",
) -> TenantContext:
    """Use restricted sub-agent context when step cap is on AgentType whitelist."""
    type_id = str(state.get("agent_type_id") or "").strip()
    if not type_id:
        return parent
    agent_type = get_agent_type(type_id)
    if agent_type is None:
        return parent
    if not capability_allowed(agent_type, step_capability_id):
        return parent
    trace_id = str(state.get("trace_id") or "")
    child = make_sub_agent_context(
        parent,
        agent_id=agent_type.type_id,
        parent_trace_id=trace_id,
    )
    perms = sorted(set(child.extra_permissions or []) | set(agent_type.permissions))
    return replace(
        child,
        extra_permissions=perms,
        risk_level=agent_type.risk_level,
    )


def ensure_spawn_ready(state: dict[str, Any]) -> None:
    """Raise if required_slots unfilled before orchestrator spawn."""
    payload = evaluate_required_slots(state)
    if payload is not None:
        raise SpawnBlockedError(payload.question, payload=payload)


def write_slots_filled(
    blackboard: Any,
    *,
    agent_type: AgentType,
    slot_values: dict[str, Any],
    tenant_id: str,
    user_id: str,
    trace_id: str,
) -> None:
    body = {
        "agent_type": agent_type.type_id,
        "filled": list(agent_type.required_slots.keys()),
        "values": {k: slot_values.get(k) for k in agent_type.required_slots},
        "source": "required_slots",
    }
    blackboard.add_topic(
        topic=TOPIC_SLOTS_FILLED,
        fact_content=json.dumps(body, ensure_ascii=False),
        source_agent_id=f"slot_gate:{agent_type.type_id}",
        document_ids_ref=[],
        confidence=1.0,
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
    )


def prepare_orchestrator_spawn(
    state: dict[str, Any],
    blackboard: Any,
) -> None:
    """Pre-flight: block on missing slots; record slots.filled when ready."""
    type_id = str(state.get("agent_type_id") or "").strip()
    if not type_id:
        return
    agent_type = get_agent_type(type_id)
    if agent_type is None:
        return
    slots = slot_values_from_state(state)
    payload = evaluate_required_slots(state)
    if payload is not None:
        missing = missing_required_slots(agent_type, slots)
        if missing:
            write_slots_missing_entry(
                blackboard,
                agent_type=agent_type,
                missing=missing,
                tenant_id=str(state.get("tenant_id") or ""),
                user_id=str(state.get("user_id") or ""),
                trace_id=str(state.get("trace_id") or ""),
            )
        raise SpawnBlockedError(payload.question, payload=payload)
    if agent_type.required_slots:
        write_slots_filled(
            blackboard,
            agent_type=agent_type,
            slot_values=slots,
            tenant_id=str(state.get("tenant_id") or ""),
            user_id=str(state.get("user_id") or ""),
            trace_id=str(state.get("trace_id") or ""),
        )
