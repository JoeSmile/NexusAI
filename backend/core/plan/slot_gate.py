"""Spawn slot gate — required_slots before AgentInstance (Task 62 / spec §2.1)."""

from __future__ import annotations

import json
from typing import Any

from .agent_type import TOPIC_SLOTS_MISSING, AgentType, get_agent_type
from .blackboard import Blackboard
from .clarification import ClarificationPayload


def slot_values_from_state(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("slot_values")
    if isinstance(raw, dict):
        return dict(raw)
    entities = state.get("entities")
    return dict(entities) if isinstance(entities, dict) else {}


def missing_required_slots(
    agent_type: AgentType,
    slot_values: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    for name in agent_type.required_slots:
        val = slot_values.get(name)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(name)
    return missing


def write_slots_missing_entry(
    blackboard: Blackboard,
    *,
    agent_type: AgentType,
    missing: list[str],
    tenant_id: str,
    user_id: str,
    trace_id: str,
) -> None:
    payload = {
        "agent_type": agent_type.type_id,
        "missing": missing,
        "hints": {k: agent_type.required_slots[k] for k in missing},
        "source": "required_slots",
    }
    blackboard.add_topic(
        topic=TOPIC_SLOTS_MISSING,
        fact_content=json.dumps(payload, ensure_ascii=False),
        source_agent_id=f"slot_gate:{agent_type.type_id}",
        document_ids_ref=[],
        confidence=1.0,
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
    )


def evaluate_required_slots(state: dict[str, Any]) -> ClarificationPayload | None:
    """Return clarification when target AgentType has unfilled required_slots."""
    type_id = str(state.get("agent_type_id") or "").strip()
    if not type_id:
        return None
    agent_type = get_agent_type(type_id)
    if agent_type is None or not agent_type.required_slots:
        return None

    missing = missing_required_slots(agent_type, slot_values_from_state(state))
    if not missing:
        return None

    hints = [f"{k}（{agent_type.required_slots[k]}）" for k in missing]
    question = (
        f"继续「{agent_type.role}」前需要补充："
        + "、".join(hints)
        + "。"
    )
    return ClarificationPayload(
        source="required_slots",
        question=question,
        options=["补充信息"],
        trace_id=str(state.get("trace_id") or ""),
        original_query=str(state.get("raw_input") or state.get("message") or ""),
    )
