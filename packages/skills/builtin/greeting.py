"""内置 Skill — 问候短路径"""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType


class GreetingSkill(BaseSkill):
    id = "greeting"
    name = "问候"
    description = "对问候意图给出快速回复"
    trigger_intents = ["greeting"]
    required_permissions: list[str] = []
    skill_type = SkillType.CODE
    short_path = True

    async def _do_execute(self, entities: dict) -> SkillResult:
        return SkillResult(
            output="你好！我是 NexusAI，有什么可以帮你的？",
            latency_ms=1.0,
        )
