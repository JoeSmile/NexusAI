"""Builtin skill — weekly social report from hotspots + analytics."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.builtin._render import entity_str, render_sections


class WeeklyReportSkill(BaseSkill):
    id = "weekly_report"
    name = "周报生成"
    description = "汇总热点与效能指标，输出社媒周报大纲"
    trigger_intents = ["content_creation"]
    required_permissions = ["chat:write", "analytics:read"]

    async def _do_execute(self, entities: dict) -> SkillResult:
        window = entity_str(entities, "window", "7d")
        body = render_sections(
            "社媒文案周报",
            [
                ("数据概览", f"统计窗口 {window}：并行拉取 hotspot.dig + analytics.summary。"),
                ("热点回顾", "Top3 话题与传播峰值（占位，接 content_ops 真数据）。"),
                ("下周计划", "延续高互动话题，安排 2 条短视频 + 1 篇长文。"),
            ],
        )
        return SkillResult(output=body)
