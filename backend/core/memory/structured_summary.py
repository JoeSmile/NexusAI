"""Structured memory summary metadata (Task 61 slice 2)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

_MAX_SHORT_SUMMARY = 250
_TOPIC_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}", re.UNICODE)


def build_structured_summary(
    *,
    doc_id: str,
    text: str,
    title: str | None = None,
    source: str = "memory",
    confidence: float = 0.7,
    time_range: str | None = None,
) -> dict[str, Any]:
    """Rule-based structured summary at write time (no LLM)."""
    raw = (text or "").strip()
    short = _first_paragraph(raw, limit=_MAX_SHORT_SUMMARY)
    topics = _extract_topics(raw)
    return {
        "doc_id": str(doc_id),
        "title": (title or short[:40] or doc_id)[:120],
        "short_summary": short,
        "key_topics": topics[:8],
        "time_range": time_range or datetime.now(UTC).strftime("%Y-%m"),
        "source": source,
        "confidence": max(0.0, min(1.0, float(confidence))),
    }


def parse_structured_summary(
    raw: str | dict[str, Any] | None,
    *,
    doc_id: str = "",
    fallback_title: str | None = None,
) -> dict[str, Any]:
    """Parse stored meta or build fallback from free text."""
    if isinstance(raw, dict):
        meta = dict(raw)
        if not meta.get("short_summary") and meta.get("summary"):
            meta["short_summary"] = _first_paragraph(str(meta["summary"]))
        return _normalize_meta(meta, doc_id=doc_id, fallback_text=raw.get("summary"))
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            return parse_structured_summary(json.loads(raw), doc_id=doc_id)
        except json.JSONDecodeError:
            pass
    text = str(raw or "")
    return build_structured_summary(
        doc_id=doc_id or "unknown",
        text=text,
        title=fallback_title,
        source="fallback",
        confidence=0.5,
    )


def format_summary_line(meta: dict[str, Any]) -> str:
    """Compact line for mode-B prompt injection."""
    doc_id = meta.get("doc_id") or "?"
    title = meta.get("title") or doc_id
    short = str(meta.get("short_summary") or "")[:_MAX_SHORT_SUMMARY]
    topics = meta.get("key_topics") or []
    topic_text = ",".join(str(t) for t in topics[:5])
    return f"[{doc_id}] {title}: {short}" + (f" (#{topic_text})" if topic_text else "")


def _normalize_meta(
    meta: dict[str, Any],
    *,
    doc_id: str,
    fallback_text: Any = None,
) -> dict[str, Any]:
    out = dict(meta)
    out["doc_id"] = str(out.get("doc_id") or doc_id or "unknown")
    if not out.get("short_summary"):
        out["short_summary"] = _first_paragraph(str(fallback_text or ""))
    if not isinstance(out.get("key_topics"), list):
        out["key_topics"] = _extract_topics(str(out.get("short_summary") or ""))
    out["confidence"] = float(out.get("confidence") or 0.5)
    out["source"] = str(out.get("source") or "memory")
    out["title"] = str(out.get("title") or out["doc_id"])[:120]
    out["time_range"] = str(out.get("time_range") or datetime.now(UTC).strftime("%Y-%m"))
    return out


def _first_paragraph(text: str, *, limit: int = _MAX_SHORT_SUMMARY) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    for sep in ("\n\n", "\n", "。", "；", ". "):
        if sep in raw:
            raw = raw.split(sep, 1)[0].strip()
            break
    if len(raw) > limit:
        return raw[: limit - 1] + "…"
    return raw


def _extract_topics(text: str, *, limit: int = 8) -> list[str]:
    tokens = _TOPIC_RE.findall((text or "").lower())
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok in seen or len(tok) < 2:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= limit:
            break
    return out
