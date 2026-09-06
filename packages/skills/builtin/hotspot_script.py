"""Builtin skill — hotspot to short video script (type=workflow)."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType


class HotspotScriptSkill(BaseSkill):
    id = "hotspot_script"
    name = "热点脚本"
    description = "将热点话题转为短视频口播脚本"
    trigger_intents = ["content_creation"]
    required_permissions = ["chat:write"]
    skill_type = SkillType.WORKFLOW
    short_path = False
    workflow_asset_id = "builtin:hotspot"
    workflow_ir = {
        "ir_schema": "1",
        "nodes": [
            {
                "node_id": "generate",
                "kind": "capability",
                "capability_id": "llm.generate",
            }
        ],
        "edges": [],
        "inputs": {
            "topic": {"name": "topic", "type": "string", "required": False},
        },
    }

    async def _do_execute(self, entities: dict) -> SkillResult:
        return SkillResult(
            success=False,
            error="WORKFLOW_USE_ENGINE",
            output="WORKFLOW_USE_ENGINE",
        )
