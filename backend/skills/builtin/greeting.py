"""内置 Skill — 问候短路径"""

from __future__ import annotations

from backend.skills.base import BaseSkill, SkillResult


class GreetingSkill(BaseSkill):
    id = "greeting"
    name = "问候"
    description = "对问候意图给出快速回复"
    trigger_intents = ["greeting"]
    required_permissions: list[str] = []

    async def _do_execute(self, entities: dict) -> SkillResult:
        return SkillResult(
            output="你好！我是 ContextGate，有什么可以帮你的？",
            latency_ms=1.0,
        )
