"""Builtin skill — social media copy (type=workflow)."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType
from packages.skills.workflow_bind import start_skill_workflow_run


class SocialCopySkill(BaseSkill):
    id = "social_copy"
    name = "社媒文案"
    description = "生成多平台社媒短文案"
    trigger_intents = ["content_creation"]
    required_permissions = ["chat:write"]
    skill_type = SkillType.WORKFLOW
    short_path = False
    cot_template = (
        "1. 明确主题与受众\n"
        "2. llm.generate 生成多平台文案"
    )
    workflow_ir = {
        "ir_schema": "1",
        "nodes": [
            {
                "node_id": "generate",
                "kind": "capability",
                "capability_id": "llm.generate",
                "params": {
                    "instruction": "根据主题生成多平台社媒短文案。",
                },
            }
        ],
        "edges": [],
        "inputs": {
            "theme": {"name": "theme", "type": "string", "required": False},
        },
    }

    async def _do_execute(
        self,
        entities: dict,
        *,
        tenant_id: str = "",
        user_context: dict | None = None,
    ) -> SkillResult:
        return start_skill_workflow_run(
            skill=self,
            entities=entities,
            tenant_id=tenant_id,
            user_context=user_context,
        )
