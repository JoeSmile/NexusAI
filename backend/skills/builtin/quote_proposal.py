"""Builtin skill — pre-sales quote proposal."""

from __future__ import annotations

from backend.skills.base import BaseSkill, SkillResult
from backend.skills.builtin._render import entity_str, render_sections


class QuoteProposalSkill(BaseSkill):
    id = "quote_proposal"
    name = "售前报价"
    description = "根据 SKU 与数量生成售前报价话术"
    trigger_intents = ["pre_sales"]
    required_permissions = ["chat:write"]

    async def _do_execute(self, entities: dict) -> SkillResult:
        sku = entity_str(entities, "sku", "标准版")
        qty = entity_str(entities, "quantity", "1")
        body = render_sections(
            "售前报价话术",
            [
                ("方案", f"产品：{sku} × {qty}"),
                ("价值点", "含实施培训、7×12 技术支持与年度安全巡检。"),
                ("下一步", "可为您生成 docx 报价单并预约演示。"),
            ],
        )
        return SkillResult(output=body)
