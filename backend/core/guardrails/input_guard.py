"""输入护栏 — Prompt 注入检测 + PII 脱敏"""

from __future__ import annotations

import re

from backend.core.guardrails.base import GuardResult
from backend.core.guardrails.injection_patterns import INJECTION_PATTERNS
from backend.core.guardrails.pii_patterns import PII_PATTERNS


async def check_input(message: str) -> GuardResult:
    """检查用户输入"""
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            return GuardResult(
                action="blocked",
                redacted_text=message,
                reason=f"injection:{pattern}",
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
