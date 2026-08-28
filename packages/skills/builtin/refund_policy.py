"""Builtin skill — refund policy playbook."""

from __future__ import annotations

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.builtin._render import entity_str, render_sections


class RefundPolicySkill(BaseSkill):
    id = "refund_policy"
    name = "退款话术"
    description = "根据订单场景生成标准退款沟通话术"
    trigger_intents = ["after_sales"]
    short_path_keywords = ["退款", "退货", "退钱", "换货", "发票"]
    required_permissions = ["chat:write"]

    async def _do_execute(self, entities: dict) -> SkillResult:
        order_id = entity_str(entities, "order_id", "（未提供订单号）")
        reason = entity_str(entities, "reason", "用户申请退款")
        body = render_sections(
            "退款处理话术",
            [
                ("开场", f"您好，已收到订单 {order_id} 的退款申请，我们会尽快处理。"),
                ("核实", f"退款原因：{reason}。请确认收货状态与支付渠道，预计 3-5 个工作日原路退回。"),
                ("收尾", "如需加急，可提供支付凭证，我们为您升级工单优先级。"),
            ],
        )
        return SkillResult(output=body)
