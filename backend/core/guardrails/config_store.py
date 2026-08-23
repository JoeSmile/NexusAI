"""Guardrail rule config store — admin console config layer (Task 67 slice 4).

Builtin rules are derived from code (read-only). Custom rules live in-process;
pipeline guardrails engine is unchanged — dry-run merges both for preview.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from backend.core.guardrails.injection_patterns import INJECTION_PATTERNS
from backend.core.guardrails.output_guard import DRIFT_PATTERNS, OUTPUT_BLOCK_PATTERNS
from backend.core.guardrails.pii_patterns import PII_PATTERNS

GuardSide = Literal["input", "output"]
GuardRuleType = Literal[
    "keyword",
    "regex",
    "pii",
    "injection",
    "length",
    "deny_list",
    "sensitive",
    "drift",
    "custom",
]
GuardAction = Literal["block", "warn", "rewrite", "sanitize"]
RiskAction = Literal["allow", "require_approval", "deny"]

DEFAULT_RISK_MATRIX: dict[str, RiskAction] = {
    "low": "allow",
    "medium": "allow",
    "high": "require_approval",
    "critical": "deny",
}

RISK_LEVELS = ("low", "medium", "high", "critical")


@dataclass
class GuardrailRule:
    id: str
    side: GuardSide
    rule_type: GuardRuleType
    name: str
    match: str
    action: GuardAction
    priority: int = 50
    enabled: bool = True
    builtin: bool = False
    description: str = ""
    updated_at: str = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_custom_rules: dict[str, GuardrailRule] = {}
_risk_matrix: dict[str, RiskAction] = dict(DEFAULT_RISK_MATRIX)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _builtin_rules() -> list[GuardrailRule]:
    rules: list[GuardrailRule] = []
    for idx, pattern in enumerate(INJECTION_PATTERNS):
        rules.append(
            GuardrailRule(
                id=f"builtin:injection:{idx}",
                side="input",
                rule_type="injection",
                name=f"注入模式 {idx + 1}",
                match=pattern,
                action="block",
                priority=100 - idx,
                enabled=True,
                builtin=True,
                description="内置 prompt 注入检测",
            )
        )
    for pii_type, pattern in PII_PATTERNS.items():
        rules.append(
            GuardrailRule(
                id=f"builtin:pii:{pii_type}",
                side="input",
                rule_type="pii",
                name=f"PII · {pii_type}",
                match=pattern,
                action="sanitize",
                priority=80,
                enabled=True,
                builtin=True,
                description="内置 PII 脱敏",
            )
        )
    rules.append(
        GuardrailRule(
            id="builtin:input:length",
            side="input",
            rule_type="length",
            name="输入长度上限",
            match="PIPELINE_MAX_INPUT_CHARS",
            action="block",
            priority=90,
            enabled=True,
            builtin=True,
            description="超长输入硬拦（与 GATE_002 同上限）",
        )
    )
    for idx, pattern in enumerate(OUTPUT_BLOCK_PATTERNS):
        rules.append(
            GuardrailRule(
                id=f"builtin:output:sensitive:{idx}",
                side="output",
                rule_type="sensitive",
                name=f"敏感输出 {idx + 1}",
                match=pattern,
                action="block",
                priority=100 - idx,
                enabled=True,
                builtin=True,
                description="内置敏感内容拦截",
            )
        )
    for idx, pattern in enumerate(DRIFT_PATTERNS):
        rules.append(
            GuardrailRule(
                id=f"builtin:output:drift:{idx}",
                side="output",
                rule_type="drift",
                name=f"角色漂移 {idx + 1}",
                match=pattern,
                action="block",
                priority=70 - idx,
                enabled=True,
                builtin=True,
                description="企业助手人设漂移检测",
            )
        )
    rules.append(
        GuardrailRule(
            id="builtin:output:length",
            side="output",
            rule_type="length",
            name="输出长度截断",
            match="4000",
            action="rewrite",
            priority=60,
            enabled=True,
            builtin=True,
            description="超长输出截断至 4000 字符",
        )
    )
    return rules


def list_rules(
    *,
    side: GuardSide | None = None,
    enabled_only: bool = False,
) -> list[GuardrailRule]:
    items = _builtin_rules() + list(_custom_rules.values())
    if side:
        items = [r for r in items if r.side == side]
    if enabled_only:
        items = [r for r in items if r.enabled]
    return sorted(items, key=lambda r: (-r.priority, r.id))


def get_rule(rule_id: str) -> GuardrailRule | None:
    for rule in list_rules():
        if rule.id == rule_id:
            return rule
    return None


def create_rule(
    *,
    side: GuardSide,
    rule_type: GuardRuleType,
    name: str,
    match: str,
    action: GuardAction,
    priority: int = 50,
    enabled: bool = True,
    description: str = "",
) -> GuardrailRule:
    rule_id = f"custom:{uuid.uuid4().hex[:12]}"
    rule = GuardrailRule(
        id=rule_id,
        side=side,
        rule_type=rule_type,
        name=name.strip() or rule_id,
        match=match.strip(),
        action=action,
        priority=priority,
        enabled=enabled,
        builtin=False,
        description=description.strip(),
        updated_at=_now_iso(),
    )
    _custom_rules[rule_id] = rule
    return rule


def update_rule(rule_id: str, patch: dict[str, Any]) -> GuardrailRule:
    existing = _custom_rules.get(rule_id)
    if existing is None:
        raise KeyError(rule_id)
    if existing.builtin:
        raise ValueError("builtin_rule_readonly")
    data = existing.to_dict()
    for key in ("side", "rule_type", "name", "match", "action", "priority", "enabled", "description"):
        if key in patch and patch[key] is not None:
            data[key] = patch[key]
    data["updated_at"] = _now_iso()
    updated = GuardrailRule(**data)
    _custom_rules[rule_id] = updated
    return updated


def delete_rule(rule_id: str) -> bool:
    existing = get_rule(rule_id)
    if existing is None:
        return False
    if existing.builtin:
        raise ValueError("builtin_rule_readonly")
    del _custom_rules[rule_id]
    return True


def get_risk_matrix() -> dict[str, str]:
    return {level: _risk_matrix.get(level, DEFAULT_RISK_MATRIX[level]) for level in RISK_LEVELS}


def update_risk_matrix(patch: dict[str, str]) -> dict[str, str]:
    for level, action in patch.items():
        if level not in RISK_LEVELS:
            continue
        normalized = str(action).strip().lower()
        if normalized in {"allow", "require_approval", "deny"}:
            _risk_matrix[level] = normalized  # type: ignore[assignment]
    return get_risk_matrix()


def resolve_risk_action(risk_level: str) -> str:
    level = str(risk_level or "low").strip().lower()
    return get_risk_matrix().get(level, "allow")


def evaluate_custom_rule(rule: GuardrailRule, text: str) -> dict[str, Any] | None:
    """Evaluate a single custom rule against text; None if no hit."""
    if not rule.enabled or rule.builtin:
        return None
    haystack = text or ""
    hit = False
    detail = ""
    if rule.rule_type in {"keyword", "deny_list"}:
        terms = [t.strip() for t in rule.match.split(",") if t.strip()]
        for term in terms:
            if term.lower() in haystack.lower():
                hit = True
                detail = term
                break
    elif rule.rule_type in {"regex", "injection", "pii", "sensitive", "drift", "custom"}:
        try:
            if re.search(rule.match, haystack, re.IGNORECASE):
                hit = True
                detail = rule.match
        except re.error:
            return {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "action": rule.action,
                "reason": "invalid_regex",
                "builtin": False,
            }
    elif rule.rule_type == "length":
        try:
            limit = int(rule.match)
            if len(haystack) > limit:
                hit = True
                detail = f"len={len(haystack)}>{limit}"
        except ValueError:
            pass
    if not hit:
        return None
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "action": rule.action,
        "reason": f"{rule.rule_type}:{detail}",
        "builtin": False,
    }


def reset_store_for_tests() -> None:
    """Test helper — clear custom rules and reset risk matrix."""
    _custom_rules.clear()
    _risk_matrix.clear()
    _risk_matrix.update(DEFAULT_RISK_MATRIX)
