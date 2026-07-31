"""Skill 注册中心 — 自动发现 + 权限传播"""

from __future__ import annotations

import importlib
import pkgutil

from backend.skills.base import BaseSkill, SkillResult


class SkillRegistry:
    """Skill 注册中心"""

    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}
        self._intent_map: dict[str, str] = {}

    def register(self, skill: BaseSkill) -> None:
        self._skills[skill.id] = skill
        for intent in skill.trigger_intents:
            self._intent_map[intent] = skill.id

    def discover(self) -> None:
        """自动扫描 builtin/ 目录"""
        try:
            import backend.skills.builtin as builtin_pkg

            for _importer, modname, _ispkg in pkgutil.iter_modules(
                builtin_pkg.__path__
            ):
                module = importlib.import_module(f"backend.skills.builtin.{modname}")
                for attr_name in dir(module):
                    cls = getattr(module, attr_name)
                    if (
                        isinstance(cls, type)
                        and issubclass(cls, BaseSkill)
                        and cls is not BaseSkill
                    ):
                        self.register(cls())
        except Exception:
            pass

    def get_skill(self, skill_id: str) -> BaseSkill | None:
        return self._skills.get(skill_id)

    def get_skill_for_intent(
        self, intent: str, confidence: float, threshold: float = 0.85
    ) -> BaseSkill | None:
        if confidence < threshold:
            return None
        skill_id = self._intent_map.get(intent)
        if skill_id:
            return self._skills.get(skill_id)
        return None

    async def execute_skill(
        self,
        skill_id: str,
        entities: dict,
        tenant_id: str,
        user_context: dict,
    ) -> SkillResult:
        skill = self._skills.get(skill_id)
        if not skill:
            return SkillResult(
                success=False, error="SKILL_001", output="Skill 未找到"
            )
        return await skill.execute(
            entities=entities,
            tenant_id=tenant_id,
            user_context=user_context,
        )


registry = SkillRegistry()
