"""Builtin meta skill — semi-auto skill extraction demo."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.builtin._render import render_sections
from packages.skills.types import SkillType


class SkillExtractSkill(BaseSkill):
    id = "skill_extract"
    name = "话术萃取"
    description = "演示从 task_plan 轨迹半自动萃取 skill_asset 草案"
    trigger_intents = ["skill_extract", "meta"]
    required_permissions = ["chat:write"]
    skill_type = SkillType.CODE
    short_path = False

    async def _do_execute(self, entities: dict) -> SkillResult:
        body = render_sections(
            "话术萃取指引",
            [
                ("输入", "收集 chat.task_plan 审计轨迹（近 N 条成功规划）。"),
                ("处理", "调用 skill_assets.miner 归纳 CoT + ir_skeleton，入库 draft。"),
                ("发布", "管理员审核后走 publish 三关（脱敏/供应链/权限）→ published。"),
            ],
        )
        return SkillResult(output=body)
