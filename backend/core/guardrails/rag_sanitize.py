"""RAG / memory fragment sanitization before prompt assembly (Task 61)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from backend.core.guardrails.injection_patterns import INJECTION_PATTERNS
from backend.core.guardrails.input_guard import detect_injection
from backend.core.memory_service import MemoryBundle

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_RAG_EXTRA_PATTERNS: tuple[str, ...] = (
    r"ignore\s+(all\s+)?(previous|prior)\s+(instructions?|prompts?)",
    r"<\|",
    r"\|\>",
    r"###\s*system\b",
    r"^\s*assistant\s*:",
    r"^\s*system\s*:",
    r"developer\s+message\s*:",
)


def _max_fragment_chars() -> int:
    try:
        return int(os.getenv("RAG_SANITIZE_MAX_FRAGMENT_CHARS", "2000") or "2000")
    except ValueError:
        return 2000


@dataclass
class RagSanitizeReport:
    retrieved_ids: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    redacted_fragments: int = 0
    truncated_fragments: int = 0

    def flag_summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.flags:
            out[f] = out.get(f, 0) + 1
        return out


def sanitize_fragment(text: str, *, max_chars: int | None = None) -> tuple[str, list[str]]:
    """Clean a single retrieved fragment; returns sanitized text + flags."""
    flags: list[str] = []
    s = (text or "").strip()
    if not s:
        return "", flags

    cleaned = _CONTROL_CHAR_RE.sub("", s)
    if cleaned != s:
        flags.append("control_chars_removed")
        s = cleaned

    if detect_injection(s):
        flags.append("injection_redacted")
        return "[SANITIZED:injection]", flags

    for pattern in _RAG_EXTRA_PATTERNS:
        if re.search(pattern, s, re.IGNORECASE | re.MULTILINE):
            s = re.sub(pattern, "[SANITIZED]", s, flags=re.IGNORECASE | re.MULTILINE)
            flags.append("pattern_redacted")

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, s, re.IGNORECASE):
            s = re.sub(pattern, "[SANITIZED]", s, flags=re.IGNORECASE)
            if "pattern_redacted" not in flags:
                flags.append("pattern_redacted")

    limit = max_chars if max_chars is not None else _max_fragment_chars()
    if len(s) > limit:
        s = s[:limit] + "…"
        flags.append("truncated")

    return s, flags


def sanitize_memory_bundle(bundle: MemoryBundle) -> tuple[MemoryBundle, RagSanitizeReport]:
    """Sanitize warm/cold/hot memory before ``assemble_prompt_block``."""
    report = RagSanitizeReport()
    max_chars = _max_fragment_chars()

    warm_out: dict[str, str] = {}
    for key, raw in (bundle.warm or {}).items():
        text, flags = sanitize_fragment(str(raw), max_chars=max_chars)
        warm_out[key] = text
        report.flags.extend(flags)
        if "injection_redacted" in flags or "pattern_redacted" in flags:
            report.redacted_fragments += 1
        if "truncated" in flags:
            report.truncated_fragments += 1

    cold_out: list[dict[str, Any]] = []
    for item in bundle.cold or []:
        row = dict(item)
        doc_id = str(row.get("id") or row.get("session_id") or row.get("memory_id") or "")
        if doc_id:
            report.retrieved_ids.append(doc_id)
        if row.get("summary"):
            text, flags = sanitize_fragment(str(row["summary"]), max_chars=max_chars)
            row["summary"] = text
            report.flags.extend(flags)
            if "injection_redacted" in flags or "pattern_redacted" in flags:
                report.redacted_fragments += 1
            if "truncated" in flags:
                report.truncated_fragments += 1
        cold_out.append(row)

    hot_out: list[dict[str, Any]] = []
    for msg in bundle.hot or []:
        row = dict(msg)
        mid = str(row.get("id") or row.get("message_id") or "")
        if mid:
            report.retrieved_ids.append(f"hot:{mid}")
        content = str(row.get("content") or "")
        if content:
            text, flags = sanitize_fragment(content, max_chars=max_chars)
            row["content"] = text
            report.flags.extend(flags)
            if "injection_redacted" in flags or "pattern_redacted" in flags:
                report.redacted_fragments += 1
            if "truncated" in flags:
                report.truncated_fragments += 1
        hot_out.append(row)

    for key in warm_out:
        if key and key not in report.retrieved_ids:
            report.retrieved_ids.append(f"warm:{key}")

    deduped: list[str] = []
    seen: set[str] = set()
    for rid in report.retrieved_ids:
        if rid not in seen:
            seen.add(rid)
            deduped.append(rid)
    report.retrieved_ids = deduped

    return (
        MemoryBundle(hot=hot_out, warm=warm_out, cold=cold_out),
        report,
    )
