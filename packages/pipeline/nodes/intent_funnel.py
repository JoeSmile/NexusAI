"""Intent funnel L1/L2 — sparse topic continue vs new (Task 77)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from packages.intent.belief_store import delete_belief, get_belief, set_belief
from packages.observability.decorators import observe
from packages.pipeline.followup_lexicon import (
    is_followup_utterance,
    is_topic_switch_utterance,
)
from packages.pipeline.state import PipelineState
from packages.plan.clarification import session_has_pending_clarification

logger = logging.getLogger(__name__)

L2_TIMEOUT_S = 3.0
L2_MAX_BELIEF_CHARS = 400
L2_MAX_TURN_CHARS = 200
L2_MAX_TURNS = 3
_L2_KEYS = ("is_new_topic", "continue_prev_task", "updated_slots", "confidence", "reason")
_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

LlmCall = Callable[..., Awaitable[str]]


def _message(state: PipelineState) -> str:
    return str(state.get("raw_input") or state.get("message") or "")


def l1_hint_new_topic(message: str) -> bool:
    return is_topic_switch_utterance(message)


def l1_recall(hot_memory: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    rows = list(hot_memory or [])[-L2_MAX_TURNS:]
    out: list[dict[str, str]] = []
    for row in rows:
        role = str(row.get("role") or "user")
        text = str(row.get("content") or row.get("text") or "")[:L2_MAX_TURN_CHARS]
        out.append({"role": role, "text": text})
    return out


def should_run_l2(
    state: PipelineState,
    *,
    belief: dict[str, Any] | None,
    hint_new_topic: bool,
) -> bool:
    if session_has_pending_clarification(state):
        return False
    if belief and str(belief.get("status") or "").upper() == "ACTIVE":
        return True
    if is_followup_utterance(_message(state)):
        return True
    return bool(hint_new_topic)


def parse_l2_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    match = _JSON_OBJ.search(text)
    if not match:
        return None
    try:
        row = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    if any(k not in row for k in _L2_KEYS):
        return None
    if not isinstance(row["is_new_topic"], bool) or not isinstance(
        row["continue_prev_task"], bool
    ):
        return None
    if row["is_new_topic"] == row["continue_prev_task"]:
        return None
    if not isinstance(row.get("updated_slots"), dict):
        return None
    try:
        conf = float(row["confidence"])
    except (TypeError, ValueError):
        return None
    reason = str(row.get("reason") or "")[:80]
    return {
        "is_new_topic": bool(row["is_new_topic"]),
        "continue_prev_task": bool(row["continue_prev_task"]),
        "updated_slots": dict(row["updated_slots"]),
        "confidence": conf,
        "reason": reason,
    }


def rule_decide(message: str, belief: dict[str, Any] | None) -> dict[str, Any]:
    if not belief or str(belief.get("status") or "").upper() != "ACTIVE":
        return {
            "is_new_topic": True,
            "continue_prev_task": False,
            "updated_slots": {},
            "confidence": 0.0,
            "reason": "no_belief",
        }
    if is_topic_switch_utterance(message):
        return {
            "is_new_topic": True,
            "continue_prev_task": False,
            "updated_slots": {},
            "confidence": 1.0,
            "reason": "topic_switch",
        }
    if is_followup_utterance(message):
        return {
            "is_new_topic": False,
            "continue_prev_task": True,
            "updated_slots": {},
            "confidence": 0.9,
            "reason": "followup",
        }
    return {
        "is_new_topic": False,
        "continue_prev_task": True,
        "updated_slots": {},
        "confidence": 0.5,
        "reason": "active_default",
    }


def _trim_belief(belief: dict[str, Any]) -> dict[str, Any]:
    summary = str(belief.get("summary") or "")[:L2_MAX_BELIEF_CHARS]
    slots = belief.get("slots") if isinstance(belief.get("slots"), dict) else {}
    return {"status": "ACTIVE", "slots": dict(slots), "summary": summary}


def _apply_decision(
    state: PipelineState,
    *,
    belief: dict[str, Any] | None,
    decision: dict[str, Any],
    message: str,
) -> None:
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    session_id = state["session_id"]
    state["is_new_topic"] = bool(decision["is_new_topic"])
    state["continue_prev_task"] = bool(decision["continue_prev_task"])
    follow = is_followup_utterance(message)
    active = bool(belief and str(belief.get("status") or "").upper() == "ACTIVE")
    if decision["is_new_topic"]:
        if belief:
            delete_belief(tenant_id, user_id, session_id)
        state["funnel_block_short_path"] = False
        return
    slots = dict(belief.get("slots") or {}) if belief else {}
    extra = decision.get("updated_slots") or {}
    if isinstance(extra, dict):
        slots.update({str(k): v for k, v in extra.items()})
    summary = str((belief or {}).get("summary") or message)[:L2_MAX_BELIEF_CHARS]
    set_belief(
        tenant_id,
        user_id,
        session_id,
        {"status": "ACTIVE", "slots": slots, "summary": summary},
    )
    state["funnel_block_short_path"] = bool(active and follow)


@observe(name="pipeline.intent_funnel")
async def run_funnel(
    state: PipelineState,
    *,
    llm_call: LlmCall | None = None,
) -> PipelineState:
    """L1 recall + sparse L2 (tenant LLM or rules). Never 500 on Redis/LLM miss."""
    message = _message(state)
    hint = l1_hint_new_topic(message)
    state["funnel_l1_hint"] = 1 if hint else 0
    state["funnel_recall"] = l1_recall(list(state.get("hot_memory") or []))
    state.setdefault("is_new_topic", False)
    state.setdefault("continue_prev_task", False)
    state.setdefault("funnel_block_short_path", False)
    state["funnel_skipped"] = None

    if session_has_pending_clarification(state):
        state["funnel_skipped"] = "clarification_pending"
        return state

    belief = get_belief(state["tenant_id"], state["user_id"], state["session_id"])
    if not should_run_l2(state, belief=belief, hint_new_topic=hint):
        state["is_new_topic"] = True
        state["continue_prev_task"] = False
        state["funnel_block_short_path"] = False
        return state

    decision: dict[str, Any] | None = None
    if is_topic_switch_utterance(message):
        decision = rule_decide(message, belief)
    else:
        active = bool(belief and str(belief.get("status") or "").upper() == "ACTIVE")
        if active and llm_call is not None:
            try:
                raw = await llm_call(
                    message=message,
                    belief=_trim_belief(belief or {}),
                    recall=state.get("funnel_recall") or [],
                )
                decision = parse_l2_json(str(raw or ""))
            except Exception:
                logger.debug("funnel L2 llm failed", exc_info=True)
                decision = None
        elif active and llm_call is None:
            decision = await _try_tenant_l2(state, belief=belief or {})

    if decision is None:
        decision = rule_decide(message, belief)
    if decision["is_new_topic"] and belief:
        from packages.intent.belief_archive import archive_ended_belief

        await archive_ended_belief(
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            session_id=state["session_id"],
            belief=belief,
        )
    _apply_decision(state, belief=belief, decision=decision, message=message)
    return state


async def intent_funnel(state: PipelineState) -> PipelineState:
    return await run_funnel(state)


async def _try_tenant_l2(
    state: PipelineState, *, belief: dict[str, Any]
) -> dict[str, Any] | None:
    import asyncio

    tenant_id = state["tenant_id"]
    try:
        from packages.llm_credentials import (
            resolve_chat_model_for_request,
            resolve_tenant_credential,
        )

        model = await asyncio.wait_for(
            resolve_chat_model_for_request(tenant_id, None),
            timeout=1.0,
        )
        cred = await asyncio.wait_for(
            resolve_tenant_credential(tenant_id, str(model)),
            timeout=1.0,
        )
    except Exception:
        return None
    prompt = (
        "Decide if the user continues the current task or starts a new topic. "
        "Reply with JSON only: "
        '{"is_new_topic": bool, "continue_prev_task": bool, '
        '"updated_slots": {}, "confidence": 0.0, "reason": ""}.\n'
        f"belief:{json.dumps(_trim_belief(belief), ensure_ascii=False)}\n"
        f"recall:{json.dumps(state.get('funnel_recall') or [], ensure_ascii=False)}\n"
        f"utterance:{_message(state)[:500]}"
    )
    try:
        from packages.harness.llm import LLMHarness

        harness = LLMHarness()
        result = await asyncio.wait_for(
            harness.generate(
                model=str(model),
                messages=[{"role": "user", "content": prompt}],
                tenant_id=tenant_id,
                api_key=cred.api_key,
                base_url=cred.base_url,
                key_id=str(cred.id),
                max_tokens=200,
                temperature=0.0,
            ),
            timeout=L2_TIMEOUT_S,
        )
        raw = getattr(result, "output", None) or ""
    except Exception:
        logger.debug("funnel L2 generate failed", exc_info=True)
        return None
    return parse_l2_json(str(raw or ""))
