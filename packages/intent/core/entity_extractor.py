"""Rule-based entity/slot extraction for L0 analyze_parallel (Phase 1 MVP)."""

from __future__ import annotations

import re

from .entity_schemas import ENTITY_SCHEMAS, SlotDef


def extract_entities(message: str, intent: str) -> dict[str, str]:
    """Extract intent-conditioned slots from user message (deterministic, no LLM)."""
    text = (message or "").strip()
    if not text:
        return {}

    key = (intent or "").strip().lower()
    schema = ENTITY_SCHEMAS.get(key) or []
    out: dict[str, str] = {}
    for slot in schema:
        value = _extract_slot(text, slot)
        if value:
            out[slot.name] = value
    return map_agent_type_slots(key, out)


def _extract_slot(text: str, slot: SlotDef) -> str:
    for pat in slot.patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            val = match.group(1).strip()
            if val:
                return val
    for trigger, mapped in slot.keywords:
        if trigger in text:
            return mapped
    return ""


def map_agent_type_slots(intent: str, entities: dict[str, str]) -> dict[str, str]:
    """Align Skill keys with AgentType required_slots aliases."""
    out = dict(entities)
    if intent == "after_sales":
        issue = out.get("issue_type", "")
        if issue in ("退款", "退货") and "reason" not in out:
            out["reason"] = issue
        if issue == "投诉" and "topic" not in out:
            out.setdefault("topic", "服务投诉")
        if "product_scope" not in out and out.get("sku"):
            out["product_scope"] = out["sku"]
    elif intent == "pre_sales":
        if "product_scope" not in out and out.get("sku"):
            out["product_scope"] = out["sku"]
    return out
