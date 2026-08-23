"""Builtin skill — social media copy."""

from __future__ import annotations

from backend.skills.base import BaseSkill, SkillResult
from backend.skills.builtin._render import entity_str, render_sections


class SocialCopySkill(BaseSkill):
    id = "social_copy"
    name = "社媒文案"
    description = "生成多平台社媒短文案"
    trigger_intents = ["social", "copywriting"]
    required_permissions = ["chat:write"]

    async def _do_execute(self, entities: dict) -> SkillResult:
        theme = entity_str(entities, "theme", "产品更新")
        body = render_sections(
            "社媒文案包",
            [
                ("微博", f"【{theme}】一文看懂本次更新亮点，转发抽体验名额。"),
                ("朋友圈", f"刚体验完 {theme}，效率提升肉眼可见，推荐试试。"),
                ("小红书", f"实测 {theme}｜3 个细节让工作流更顺，附操作清单。"),
            ],
        )
        return SkillResult(output=body)
