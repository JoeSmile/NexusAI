"""Guardrail dry-run — preview hits without mutating pipeline state (Task 67)."""

from __future__ import annotations

from typing import Any, Literal

from packages.guardrails.config_store import (
    GuardSide,
    evaluate_custom_rule,
    list_rules,
    resolve_risk_action,
)
from packages.guardrails.input_guard import check_input
from packages.guardrails.output_guard import check_output

GuardEngineAction = Literal["pass", "redacted", "blocked", "truncated", "warn"]


def _map_engine_action(action: str) -> str:
    if action == "redacted":
        return "sanitize"
    if action == "truncated":
        return "rewrite"
    if action == "blocked":
        return "block"
    return "pass"


async def dry_run(
    *,
    side: GuardSide,
    text: str,
    risk_level: str | None = None,
) -> dict[str, Any]:
    """Run builtin guardrails + custom rules; return preview payload."""
    hits: list[dict[str, Any]] = []
    final_action: GuardEngineAction = "pass"
    output_text = text

    if side == "input":
        engine = await check_input(text)
    else:
        engine = await check_output(text)

    if engine.action != "pass":
        hits.append(
            {
                "rule_id": "builtin:engine",
                "rule_name": "内置护栏引擎",
                "action": _map_engine_action(engine.action),
                "reason": engine.reason,
                "builtin": True,
            }
        )
        final_action = engine.action  # type: ignore[assignment]
        output_text = engine.redacted_text

    for rule in list_rules(side=side, enabled_only=True):
        if rule.builtin:
            continue
        custom_hit = evaluate_custom_rule(rule, text)
        if custom_hit:
            hits.append(custom_hit)
            if custom_hit["action"] == "block":
                final_action = "blocked"
                output_text = "[BLOCKED BY CUSTOM RULE]"
            elif custom_hit["action"] == "warn" and final_action == "pass":
                final_action = "warn"
            elif custom_hit["action"] == "sanitize" and final_action == "pass":
                final_action = "redacted"
            elif custom_hit["action"] == "rewrite" and final_action == "pass":
                final_action = "truncated"

    risk_policy: dict[str, Any] | None = None
    if risk_level:
        action = resolve_risk_action(risk_level)
        risk_policy = {"risk_level": risk_level.strip().lower(), "action": action}

    return {
        "side": side,
        "final_action": final_action,
        "output_text": output_text,
        "hits": hits,
        "risk_policy": risk_policy,
    }
