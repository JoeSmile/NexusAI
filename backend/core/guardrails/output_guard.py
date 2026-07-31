"""输出护栏 — 长度截断 + 敏感内容 + 角色漂移"""

from __future__ import annotations

import re

from backend.core.guardrails.base import GuardResult

OUTPUT_BLOCK_PATTERNS = [
    r"API密钥",
    r"sk-[a-zA-Z0-9]{10,}",
    r"SECRET_KEY",
    r"PASSWORD",
]

DRIFT_PATTERNS = [
    r"点击.*链接",
    r"限时.*优惠",
    r"下单.*购买",
    r"直播间.*关注",
    r"家人们.*",
    r"买了.*不亏",
    r"错过.*后悔",
]

VIOLATION_PATTERNS = [
    r"sk-[a-zA-Z0-9]{10,}",
    r"SECRET_KEY",
]


async def check_role_drift(response: str) -> GuardResult:
    for pattern in DRIFT_PATTERNS:
        if re.search(pattern, response):
            return GuardResult(
                action="blocked",
                redacted_text="[OUTPUT BLOCKED: 角色漂移]",
                reason=f"role_drift:{pattern}",
            )
    return GuardResult(action="pass", redacted_text=response, reason="")


async def check_output(response: str) -> GuardResult:
    """检查 LLM 输出"""
    if len(response) > 4000:
        return GuardResult(
            action="truncated",
            redacted_text=response[:4000],
            reason="length_exceeded",
        )

    for pattern in OUTPUT_BLOCK_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            return GuardResult(
                action="blocked",
                redacted_text="[OUTPUT BLOCKED: 包含敏感内容]",
                reason=f"sensitive_content:{pattern}",
            )

    drift = await check_role_drift(response)
    if drift.action == "blocked":
        return drift

    return GuardResult(action="pass", redacted_text=response, reason="")
