"""Builtin skill — complaint escalation with approval gate."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.builtin._render import entity_str, render_sections
from packages.skills.types import SkillType


class ComplaintEscalationSkill(BaseSkill):
    id = "complaint_escalation"
    name = "投诉升级"
    description = "高优先级投诉升级话术，触发人工审批"
    trigger_intents = ["after_sales"]
    short_path_keywords = ["投诉", "升级", "差评", "举报"]
    required_permissions = ["chat:write"]
    requires_human_approval = True
    skill_type = SkillType.CODE
    short_path = True
    cot_template = (
        "1. 记录投诉摘要与严重级别\n"
        "2. 触发审批（REQUIRE_APPROVAL）\n"
        "3. 通过后 im.notify 升级工单"
    )
    ir_skeleton = {
        "steps": [
            {
                "id": "draft",
                "capability_id": "mail.draft",
                "params": {"subject": "complaint escalation"},
                "depends_on": [],
            },
            {
                "id": "notify",
                "capability_id": "im.notify",
                "params": {"type": "escalation", "summary": "complaint"},
                "depends_on": ["draft"],
            },
        ]
    }

    async def _do_execute(
        self,
        entities: dict,
        *,
        tenant_id: str = "",
        user_context: dict | None = None,
    ) -> SkillResult:
        topic = entity_str(entities, "topic", "服务投诉")
        body = render_sections(
            "投诉升级草案",
            [
                ("摘要", f"用户投诉主题：{topic}"),
                ("升级动作", "转交值班主管，2 小时内回电；同步 im.notify 通知客服组长。"),
            ],
        )
        return SkillResult(output=body)
