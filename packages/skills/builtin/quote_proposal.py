"""Builtin skill — pre-sales quote proposal (type=workflow)."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType


class QuoteProposalSkill(BaseSkill):
    id = "quote_proposal"
    name = "售前报价"
    description = "根据 SKU 与数量生成售前报价话术"
    trigger_intents = ["pre_sales"]
    required_permissions = ["chat:write"]
    skill_type = SkillType.WORKFLOW
    short_path = False
    workflow_ir = {
        "ir_schema": "1",
        "nodes": [
            {
                "node_id": "docx",
                "kind": "capability",
                "capability_id": "docx.generate",
                "params": {"template": "quote"},
            }
        ],
        "edges": [],
        "inputs": {
            "sku": {"name": "sku", "type": "string", "required": True},
            "qty": {"name": "qty", "type": "string", "required": True},
        },
    }

    async def _do_execute(self, entities: dict) -> SkillResult:
        return SkillResult(
            success=False,
            error="WORKFLOW_USE_ENGINE",
            output="WORKFLOW_USE_ENGINE",
        )
