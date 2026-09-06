"""Builtin skill — hotspot to short video script (type=workflow)."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType
from packages.skills.workflow_bind import start_skill_workflow_run


class HotspotScriptSkill(BaseSkill):
    id = "hotspot_script"
    name = "热点脚本"
    description = "将热点话题转为短视频口播脚本"
    trigger_intents = ["content_creation"]
    required_permissions = ["chat:write"]
    skill_type = SkillType.WORKFLOW
    short_path = False
    cot_template = (
        "1. 解析选题 / 热点意图\n"
        "2. 走 builtin:hotspot published workflow（或 llm.generate fallback）\n"
        "3. 产出口播脚本"
    )
    workflow_asset_id = "builtin:hotspot"
    workflow_ir = {
        "ir_schema": "1",
        "nodes": [
            {
                "node_id": "generate",
                "kind": "capability",
                "capability_id": "llm.generate",
                "params": {
                    "instruction": "根据选题生成短视频口播脚本。",
                },
            }
        ],
        "edges": [],
        "inputs": {
            "topic": {"name": "topic", "type": "string", "required": False},
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
