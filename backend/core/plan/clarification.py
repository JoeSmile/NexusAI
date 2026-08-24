"""Clarification loop — trigger evaluation + session pending state (Task 65 slice 6)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.core.audit import write_audit_sync
from backend.core.audit_context import get_audit_lineage

logger = logging.getLogger(__name__)

# L0 三档：低于此值触发澄清（与 intent_path SHORT_PATH 0.85 对齐）
CLARIFY_CONFIDENCE_MAX = 0.4
PENDING_TTL_S = 60
_HIGH_RISK_LEVELS = frozenset({"high", "critical"})
WARM_KEY_PREFIX = "clarify_pending:"


@dataclass
class ClarificationPayload:
    source: str
    question: str
    options: list[str] = field(default_factory=list)
    trace_id: str = ""
    original_query: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "question": self.question,
            "options": list(self.options),
            "trace_id": self.trace_id,
            "original_query": self.original_query,
            "created_at": self.created_at,
        }


def warm_pending_key(session_id: str) -> str:
    return f"{WARM_KEY_PREFIX}{session_id or 'default'}"


def _parse_pending_value(raw: str) -> dict[str, Any] | None:
    try:
        row = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return row if isinstance(row, dict) else None


def _pending_from_warm(state: dict[str, Any]) -> dict[str, Any] | None:
    key = warm_pending_key(str(state.get("session_id") or "default"))
    warm = dict(state.get("warm_memory") or {})
    raw = warm.get(key)
    if not raw:
        return None
    return _parse_pending_value(str(raw))


async def _fetch_pending_from_db(state: dict[str, Any]) -> dict[str, Any] | None:
    tenant_id = str(state.get("tenant_id") or "")
    user_id = str(state.get("user_id") or "")
    if not tenant_id or not user_id:
        return None
    key = warm_pending_key(str(state.get("session_id") or "default"))
    try:
        from backend.database.vector_ops import list_user_memories_by_prefix

        rows = list_user_memories_by_prefix(tenant_id, user_id, key, limit=1)
    except Exception:
        logger.warning("fetch clarification pending failed key=%s", key, exc_info=True)
        return None
    if not rows:
        return None
    row = _parse_pending_value(str(rows[0].get("value") or ""))
    if row is not None:
        warm = dict(state.get("warm_memory") or {})
        warm[key] = rows[0]["value"]
        state["warm_memory"] = warm
    return row


async def get_pending(
    state: dict[str, Any],
    *,
    audit_on_timeout: bool = False,
) -> dict[str, Any] | None:
    row = _pending_from_warm(state)
    if row is None:
        row = await _fetch_pending_from_db(state)
    if not row:
        return None

    created = float(row.get("created_at") or 0)
    if created and (time.time() - created) > PENDING_TTL_S:
        await clear_pending(state)
        if audit_on_timeout:
            audit_clarification_event(
                tenant_id=str(state.get("tenant_id") or ""),
                user_id=str(state.get("user_id") or ""),
                trace_id=str(state.get("trace_id") or row.get("trace_id") or ""),
                event="timeout",
                payload=dict(row),
            )
        return None
    return row


async def store_pending(state: dict[str, Any], payload: ClarificationPayload) -> None:
    tenant_id = str(state.get("tenant_id") or "")
    user_id = str(state.get("user_id") or "")
    session_id = str(state.get("session_id") or "default")
    key = warm_pending_key(session_id)
    value = json.dumps(payload.to_dict(), ensure_ascii=False)

    from backend.core.memory_service import get_unified_memory_service

    mem = get_unified_memory_service(tenant_id=tenant_id)
    await mem.write(
        "warm",
        user_id=user_id,
        key=key,
        value=value,
        confidence=1.0,
        source="clarification",
        embed=False,
    )
    warm = dict(state.get("warm_memory") or {})
    warm[key] = value
    state["warm_memory"] = warm


async def clear_pending(state: dict[str, Any]) -> None:
    tenant_id = str(state.get("tenant_id") or "")
    user_id = str(state.get("user_id") or "")
    session_id = str(state.get("session_id") or "default")
    key = warm_pending_key(session_id)

    from backend.database.vector_ops import delete_user_memory

    try:
        delete_user_memory(tenant_id, user_id, key)
    except Exception:
        logger.warning("clear clarification pending failed key=%s", key, exc_info=True)

    warm = dict(state.get("warm_memory") or {})
    warm.pop(key, None)
    state["warm_memory"] = warm


def _query_rewrite(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("query_rewrite")
    return dict(raw) if isinstance(raw, dict) else {}


def _high_risk_incomplete_steps(plan: dict[str, Any]) -> list[str]:
    from backend.core.capability.registry import get_capability_registry

    reg = get_capability_registry()
    missing: list[str] = []
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        cap_id = str(step.get("capability_id") or "")
        if not cap_id:
            continue
        try:
            spec = reg.get(cap_id, require_enabled=False)
        except Exception:
            continue
        nested = dict(spec.spec or {})
        risk = str(nested.get("risk_level") or "low").lower()
        if risk not in _HIGH_RISK_LEVELS:
            continue
        params = dict(step.get("params") or {})
        if not params or all(not str(v).strip() for v in params.values()):
            missing.append(cap_id)
    return missing


async def hold_for_clarification(
    state: dict[str, Any],
    payload: ClarificationPayload,
    *,
    clear_task_plan: bool = True,
) -> dict[str, Any]:
    """Apply clarification hold — shared by clarification_gate and orchestrator fallback."""
    from backend.core.plan.event_bus import bus_for_state

    body = payload.to_dict()
    state["pending_clarification"] = True
    state["clarification"] = body
    state["response"] = payload.question
    state["finish_reason"] = "clarification_pending"
    state["clarification_resolved"] = False
    if clear_task_plan:
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
    return state


def evaluate_clarification_triggers(state: dict[str, Any]) -> ClarificationPayload | None:
    """Return clarification payload when a trigger fires; None to continue pipeline."""
    from backend.core.plan.slot_gate import evaluate_required_slots

    slot_payload = evaluate_required_slots(state)
    if slot_payload is not None:
        return slot_payload

    if state.get("clarification_resolved"):
        return None

    message = str(state.get("raw_input") or state.get("message") or "").strip()
    trace_id = str(state.get("trace_id") or "")

    confidence = float(state.get("intent_confidence") or 0.0)
    if confidence < CLARIFY_CONFIDENCE_MAX:
        return ClarificationPayload(
            source="low_confidence",
            question="我不太确定您的具体意图，能否再说明一下您想完成什么？",
            options=["补充细节", "换个说法"],
            trace_id=trace_id,
            original_query=message,
        )

    qr = _query_rewrite(state)
    if qr.get("clarification_needed"):
        return ClarificationPayload(
            source="rewrite_flag",
            question="需要再确认一下：您希望我具体帮您做什么？",
            options=["说明目标", "提供更多信息"],
            trace_id=trace_id,
            original_query=message,
        )

    plan = state.get("task_plan")
    if isinstance(plan, dict):
        risky = _high_risk_incomplete_steps(plan)
        if risky:
            return ClarificationPayload(
                source="high_risk_tool",
                question=f"执行「{risky[0]}」前需要补充参数，请说明具体对象或范围。",
                options=["补充参数"],
                trace_id=trace_id,
                original_query=message,
            )

    suggested = str(qr.get("suggested_intent") or state.get("intent") or "")
    entities = dict(state.get("entities") or {})
    if suggested in {"knowledge_query", "function"} and not entities:
        if len(message) < 12 or "?" in message or "吗" in message:
            return ClarificationPayload(
                source="missing_entities",
                question="请问您指的是哪个对象、时间范围或具体场景？",
                options=["指定对象", "指定时间"],
                trace_id=trace_id,
                original_query=message,
            )

    return None


async def try_resolve_pending(state: dict[str, Any]) -> bool:
    """If session has pending clarification, merge user answer and continue."""
    pending = await get_pending(state)
    if not pending:
        return False

    answer = str(state.get("message") or "").strip()
    if not answer:
        return False

    original = str(pending.get("original_query") or "").strip()
    merged = f"{original}（补充：{answer}）" if original else answer
    state["message"] = merged
    state["raw_input"] = merged
    state["query_rewrite"] = {
        "rewritten_query": merged,
        "sub_queries": [merged],
        "language": "zh",
        "clarification_needed": False,
    }
    state["clarification_resolved"] = True
    state["pending_clarification"] = False
    state["clarification"] = None
    state["task_plan"] = None

    await clear_pending(state)
    audit_clarification_event(
        tenant_id=str(state.get("tenant_id") or ""),
        user_id=str(state.get("user_id") or ""),
        trace_id=str(state.get("trace_id") or pending.get("trace_id") or ""),
        event="resolved",
        payload={
            "source": pending.get("source"),
            "answer": answer[:500],
            "merged_query": merged[:500],
        },
    )
    return True


def audit_clarification_event(
    *,
    tenant_id: str,
    user_id: str,
    trace_id: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    lineage = get_audit_lineage()
    body = {"event": event, **payload}
    detail = json.dumps(body, ensure_ascii=False)
    write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id or "user",
            "action": "chat.clarify",
            "trace_id": trace_id or lineage.trace_id or "clarify",
            "parent_trace_id": lineage.parent_trace_id,
            "tool_use_id": lineage.tool_use_id,
            "input_text": str(payload.get("source") or event)[:200],
            "output_text": detail[:4000],
            "decision_explain": detail[:4000],
        }
    )
