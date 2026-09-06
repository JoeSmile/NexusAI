"""Builtin skill — weekly report (type=workflow)."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType
from packages.skills.workflow_bind import start_skill_workflow_run


class WeeklyReportSkill(BaseSkill):
    id = "weekly_report"
    name = "周报生成"
    description = "汇总热点与效能指标，输出社媒周报大纲"
    trigger_intents = ["content_creation"]
    required_permissions = ["chat:write", "analytics:read"]
    skill_type = SkillType.WORKFLOW
    short_path = False
    workflow_ir = {
        "ir_schema": "1",
        "nodes": [
            {
                "node_id": "summary",
                "kind": "capability",
                "capability_id": "analytics.summary",
            },
            {
                "node_id": "generate",
                "kind": "capability",
                "capability_id": "llm.generate",
            },
        ],
        "edges": [
            {
                "from_node_id": "summary",
                "from_field": "result",
                "to_node_id": "generate",
                "to_param": "instruction",
            }
        ],
        "inputs": {
            "window": {"name": "window", "type": "string", "required": False},
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
