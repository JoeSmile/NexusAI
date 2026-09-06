"""Skill 注册中心 — 显式 SKILL_REGISTRY + 权限传播"""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.builtin.complaint_escalation import ComplaintEscalationSkill
from packages.skills.builtin.greeting import GreetingSkill
from packages.skills.builtin.hotspot_script import HotspotScriptSkill
from packages.skills.builtin.quote_proposal import QuoteProposalSkill
from packages.skills.builtin.refund_policy import RefundPolicySkill
from packages.skills.builtin.skill_extract import SkillExtractSkill
from packages.skills.builtin.social_copy import SocialCopySkill
from packages.skills.builtin.weekly_report import WeeklyReportSkill
from packages.skills.types import SkillType

SKILL_REGISTRY: dict[str, BaseSkill] = {
    "greeting": GreetingSkill(),
    "refund_policy": RefundPolicySkill(),
    "complaint_escalation": ComplaintEscalationSkill(),
    "quote_proposal": QuoteProposalSkill(),
    "hotspot_script": HotspotScriptSkill(),
    "social_copy": SocialCopySkill(),
    "weekly_report": WeeklyReportSkill(),
    "skill_extract": SkillExtractSkill(),
}


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

    def load(self) -> None:
        self._skills = dict(SKILL_REGISTRY)
        self._intent_map = {}
        for skill in self._skills.values():
            self._assert_executable(skill)
            self.register(skill)

    def _assert_executable(self, skill: BaseSkill) -> None:
        """规则 16：WorkflowIR.model_validate 或非空逻辑键。"""
        from packages.workflow.ir import WorkflowIR

        if skill.skill_type != SkillType.WORKFLOW:
            return
        if skill.workflow_ir:
            try:
                WorkflowIR.model_validate(skill.workflow_ir)
            except Exception as exc:
                raise ValueError(
                    f"skill {skill.id}: workflow_ir invalid: {exc}"
                ) from exc
            return
        if (skill.workflow_asset_id or "").strip():
            return
        raise ValueError(
            f"skill {skill.id}: type=workflow 必须有可校验 workflow_ir 或 "
            "workflow_asset_id 逻辑键"
        )

    discover = load

    def list_routable(self, tenant_id: str) -> list[BaseSkill]:
        out: list[BaseSkill] = []
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            allow = skill.tenant_allowlist
            if allow and tenant_id not in allow:
                continue
            if skill.skill_type == SkillType.AGENT:
                continue
            out.append(skill)
        return out

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
