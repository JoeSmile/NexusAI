"""Builtin skill — hotspot to short video script."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.builtin._render import entity_str, render_sections


class HotspotScriptSkill(BaseSkill):
    id = "hotspot_script"
    name = "热点脚本"
    description = "将热点话题转为短视频口播脚本"
    trigger_intents = ["content_creation"]
    required_permissions = ["chat:write"]

    async def _do_execute(self, entities: dict) -> SkillResult:
        topic = entity_str(entities, "topic", "本周行业热点")
        body = render_sections(
            "热点口播脚本",
            [
                ("Hook", f"你知道最近「{topic}」为什么刷屏吗？30 秒讲清楚。"),
                ("要点", "1) 背景 2) 影响 3) 行动建议"),
                ("CTA", "关注账号，下周继续拆解趋势。"),
            ],
        )
        return SkillResult(output=body)
