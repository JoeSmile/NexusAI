"""Sanitize untrusted tool output before it enters LLM context (Task 62 slice 3)."""

from __future__ import annotations

import re

from packages.plan.llm_output_guard import detect_fake_tool_call_text

_STRIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<tool_call[\s\S]*?</tool_call>", re.IGNORECASE),
    re.compile(r"<function=[^>]+>[\s\S]*?</function>", re.IGNORECASE),
    re.compile(r'"tool_calls"\s*:\s*\[[\s\S]*?\]', re.IGNORECASE),
)


def sanitize_tool_output(text: str) -> str:
    """Neutralize forged tool-call markers in capability / MCP output."""
    if not text or not detect_fake_tool_call_text(text):
        return text
    cleaned = text
    for pattern in _STRIP_PATTERNS:
        cleaned = pattern.sub("[tool_output_sanitized]", cleaned)
    if detect_fake_tool_call_text(cleaned):
        return "[untrusted_tool_output_removed]"
    return cleaned
