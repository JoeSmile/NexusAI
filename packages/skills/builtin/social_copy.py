"""Builtin skill — social media copy (type=workflow)."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType


class SocialCopySkill(BaseSkill):
    id = "social_copy"
    name = "社媒文案"
    description = "生成多平台社媒短文案"
    trigger_intents = ["content_creation"]
    required_permissions = ["chat:write"]
    skill_type = SkillType.WORKFLOW
    short_path = False
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
            "theme": {"name": "theme", "type": "string", "required": False},
        },
    }

    async def _do_execute(self, entities: dict) -> SkillResult:
        return SkillResult(
            success=False,
            error="WORKFLOW_USE_ENGINE",
            output="WORKFLOW_USE_ENGINE",
        )
