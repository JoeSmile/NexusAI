"""Shared render helpers for builtin skills (Task 66 slice 2)."""

from __future__ import annotations

from typing import Any


def render_sections(title: str, sections: list[tuple[str, str]]) -> str:
    lines = [f"## {title}", ""]
    for heading, body in sections:
        lines.append(f"### {heading}")
        lines.append(body.strip())
        lines.append("")
    return "\n".join(lines).strip()


def entity_str(entities: dict[str, Any], key: str, default: str = "") -> str:
    val = entities.get(key)
    if val is None:
        return default
    return str(val).strip()
