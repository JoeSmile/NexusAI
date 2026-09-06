"""Derive skill_assets catalog rows from SKILL_REGISTRY (Task 3)."""

from __future__ import annotations

from packages.skill_assets.types import BuiltinSkillAssetDef
from packages.skills.registry import SKILL_REGISTRY
from packages.skills.types import SkillType


def _ir_skeleton_for(skill) -> dict:
    if skill.skill_type == SkillType.WORKFLOW and skill.workflow_ir:
        # Engine-true snapshot; not the legacy steps[] draft.
        return dict(skill.workflow_ir)
    raw = getattr(skill, "ir_skeleton", None) or {}
    return dict(raw)


def builtin_asset_entries() -> list[BuiltinSkillAssetDef]:
    rows: list[BuiltinSkillAssetDef] = []
    for skill in SKILL_REGISTRY.values():
        cot = getattr(skill, "cot_template", "") or ""
        if not cot:
            continue
        rows.append(
            {
                "skill_id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "cot_template": cot,
                "ir_skeleton": _ir_skeleton_for(skill),
                "required_permissions": list(skill.required_permissions or []),
                "visibility": "tenant_public",
            }
        )
    return rows
