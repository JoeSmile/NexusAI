"""Typed shapes for skill_assets builtin catalog."""

from __future__ import annotations

from typing import Any, TypedDict


class BuiltinSkillAssetDef(TypedDict):
    skill_id: str
    name: str
    description: str
    cot_template: str
    ir_skeleton: dict[str, Any]
    required_permissions: list[str]
    visibility: str
