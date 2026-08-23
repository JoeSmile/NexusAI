"""Builtin skill — complaint escalation with approval gate."""

from __future__ import annotations

from backend.skills.base import BaseSkill, SkillResult
from backend.skills.builtin._render import entity_str, render_sections


class ComplaintEscalationSkill(BaseSkill):
    id = "complaint_escalation"
    name = "投诉升级"
    description = "高优先级投诉升级话术，触发人工审批"
    trigger_intents = ["complaint", "escalation"]
    required_permissions = ["chat:write"]
    requires_human_approval = True

    async def _do_execute(self, entities: dict) -> SkillResult:
        topic = entity_str(entities, "topic", "服务投诉")
        body = render_sections(
            "投诉升级草案",
            [
                ("摘要", f"用户投诉主题：{topic}"),
                ("升级动作", "转交值班主管，2 小时内回电；同步 im.notify 通知客服组长。"),
            ],
        )
        return SkillResult(output=body)
