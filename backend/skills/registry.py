"""Skill 注册中心 — 自动发现 + 权限传播"""

from __future__ import annotations

import importlib
import pkgutil

from backend.skills.base import BaseSkill, SkillResult


class SkillRegistry:
    """Skill 注册中心"""

    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}
        self._intent_map: dict[str, list[str]] = {}

    def register(self, skill: BaseSkill) -> None:
        self._skills[skill.id] = skill
        for intent in skill.trigger_intents:
            bucket = self._intent_map.setdefault(intent, [])
            if skill.id not in bucket:
                bucket.append(skill.id)

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
        self,
        intent: str,
        confidence: float,
        threshold: float = 0.85,
        *,
        text: str = "",
    ) -> BaseSkill | None:
        if confidence < threshold:
            return None
        skill_ids = self._intent_map.get(intent)
        if not skill_ids:
            return None
        if len(skill_ids) == 1:
            return self._skills.get(skill_ids[0])
        text_l = (text or "").lower()
        best_id: str | None = None
        best_score = -1
        for sid in skill_ids:
            skill = self._skills.get(sid)
            if skill is None:
                continue
            keywords = list(getattr(skill, "short_path_keywords", None) or [])
            score = sum(1 for kw in keywords if kw and kw in text_l)
            if score > best_score:
                best_score = score
                best_id = sid
        if best_id and best_score >= 0:
            return self._skills.get(best_id)
        return self._skills.get(skill_ids[0])

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
