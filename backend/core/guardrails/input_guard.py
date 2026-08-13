"""输入护栏 — Prompt 注入检测 + PII 脱敏"""

from __future__ import annotations

import re
from typing import Any

from backend.core.guardrails.base import GuardResult
from backend.core.guardrails.injection_patterns import INJECTION_PATTERNS
from backend.core.guardrails.pii_patterns import PII_PATTERNS


def detect_injection(text: str) -> str | None:
    """纯函数：命中返回 pattern 字符串，否则 None（不脱敏）。"""
    if not text:
        return None
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def _iter_param_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_param_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_param_strings(v)


def detect_injection_in_params(params: dict[str, Any] | None) -> str | None:
    """递归扫 params 字符串值；返回首个命中 pattern。"""
    if not params:
        return None
    for s in _iter_param_strings(params):
        hit = detect_injection(s)
        if hit:
            return hit
    return None


async def check_input(message: str) -> GuardResult:
    """检查用户输入"""
    hit = detect_injection(message)
    if hit:
        return GuardResult(
            action="blocked",
            redacted_text=message,
            reason=f"injection:{hit}",
        )

    redacted = message
    for pii_type, pattern in PII_PATTERNS.items():
        redacted = re.sub(pattern, f"[REDACTED:{pii_type}]", redacted)

    if redacted != message:
        return GuardResult(
            action="redacted",
            redacted_text=redacted,
            reason="pii_found",
        )

    if len(message) > 10000:
        return GuardResult(
            action="redacted",
            redacted_text=message[:10000],
            reason="length_exceeded",
        )

    return GuardResult(action="pass", redacted_text=message, reason="")
