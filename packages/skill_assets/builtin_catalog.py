"""Builtin skill_asset catalog — re-export derived from SKILL_REGISTRY."""

from __future__ import annotations

from packages.skill_assets.types import BuiltinSkillAssetDef
from packages.skills.catalog import builtin_asset_entries

BUILTIN_SKILL_ASSET_CATALOG: list[BuiltinSkillAssetDef] = builtin_asset_entries()
BUILTIN_SKILL_IDS = frozenset(d["skill_id"] for d in BUILTIN_SKILL_ASSET_CATALOG)

__all__ = [
    "BuiltinSkillAssetDef",
    "BUILTIN_SKILL_ASSET_CATALOG",
    "BUILTIN_SKILL_IDS",
]
