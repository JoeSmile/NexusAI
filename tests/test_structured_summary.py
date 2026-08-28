"""Structured memory summary (Task 61 slice 2)."""

from __future__ import annotations

from packages.memory.structured_summary import (
    build_structured_summary,
    format_summary_line,
    parse_structured_summary,
)


def test_build_structured_summary_limits_short_text() -> None:
    text = "第一段摘要。" + ("x" * 400)
    meta = build_structured_summary(doc_id="1", text=text, title="t")
    assert len(meta["short_summary"]) <= 250
    assert meta["doc_id"] == "1"
    assert meta["key_topics"]


def test_parse_structured_summary_fallback_first_paragraph() -> None:
    meta = parse_structured_summary("line1\n\nline2", doc_id="9")
    assert meta["short_summary"] == "line1"
    assert meta["doc_id"] == "9"


def test_format_summary_line_includes_doc_id() -> None:
    line = format_summary_line(
        {
            "doc_id": "cold:3",
            "title": "会话",
            "short_summary": "用户讨论了天气",
            "key_topics": ["天气"],
        }
    )
    assert "[cold:3]" in line
    assert "天气" in line
