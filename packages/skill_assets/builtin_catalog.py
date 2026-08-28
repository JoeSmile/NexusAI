"""Builtin skill_asset catalog (Task 66 slice 2).

Each entry maps a playbook skill to skill_assets CoT + PlanIR skeleton.
"""

from __future__ import annotations

from typing import Any, TypedDict


class BuiltinSkillAssetDef(TypedDict):
    skill_id: str
    name: str
    description: str
    cot_template: str
    ir_skeleton: dict[str, Any]
    required_permissions: list[str]
    visibility: str


def _step(
    step_id: str,
    capability_id: str,
    *,
    params: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "capability_id": capability_id,
        "params": dict(params or {}),
        "depends_on": list(depends_on or []),
    }


BUILTIN_SKILL_ASSET_CATALOG: list[BuiltinSkillAssetDef] = [
    {
        "skill_id": "refund_policy",
        "name": "refund_policy",
        "description": "标准退款沟通话术与核实清单",
        "cot_template": (
            "1. 确认订单与支付渠道\n"
            "2. 核对退款原因与收货状态\n"
            "3. 给出时效预期与加急路径"
        ),
        "ir_skeleton": {
            "steps": [
                _step("mem", "memory.search", params={"query": "order refund history"}),
                _step("notify", "im.notify", params={"type": "refund", "summary": "refund ticket"}, depends_on=["mem"]),
            ]
        },
        "required_permissions": ["chat:write", "memory:read"],
        "visibility": "tenant_public",
    },
    {
        "skill_id": "complaint_escalation",
        "name": "complaint_escalation",
        "description": "投诉升级：审批后通知值班主管",
        "cot_template": (
            "1. 记录投诉摘要与严重级别\n"
            "2. 触发审批（REQUIRE_APPROVAL）\n"
            "3. 通过后 im.notify 升级工单"
        ),
        "ir_skeleton": {
            "steps": [
                _step("draft", "mail.draft", params={"subject": "complaint escalation"}),
                _step("notify", "im.notify", params={"type": "escalation", "summary": "complaint"}, depends_on=["draft"]),
            ]
        },
        "required_permissions": ["chat:write"],
        "visibility": "tenant_public",
    },
    {
        "skill_id": "quote_proposal",
        "name": "quote_proposal",
        "description": "售前报价：检索产品资料并生成报价草案",
        "cot_template": (
            "1. rag.search 拉取产品规格\n"
            "2. 组合 SKU 与数量\n"
            "3. docx.generate 输出报价单"
        ),
        "ir_skeleton": {
            "steps": [
                _step("rag", "rag.search", params={"query": "product pricing"}),
                _step("doc", "docx.generate", params={"template": "quote"}, depends_on=["rag"]),
            ]
        },
        "required_permissions": ["chat:write", "rag:read"],
        "visibility": "tenant_public",
    },
    {
        "skill_id": "hotspot_script",
        "name": "hotspot_script",
        "description": "热点挖掘后生成短视频脚本",
        "cot_template": (
            "1. hotspot.dig 抓取热点\n"
            "2. 选取 Top 话题\n"
            "3. 生成口播脚本"
        ),
        "ir_skeleton": {
            "steps": [
                _step("dig", "hotspot.dig", params={"window": "24h"}),
                _step("script", "script.gen", params={"format": "short_video"}, depends_on=["dig"]),
            ]
        },
        "required_permissions": ["chat:write"],
        "visibility": "tenant_public",
    },
    {
        "skill_id": "social_copy",
        "name": "social_copy",
        "description": "多平台社媒文案生成",
        "cot_template": (
            "1. 明确主题与受众\n"
            "2. 生成微博/朋友圈/小红书三版文案\n"
            "3. 可选 web.search 补充事实"
        ),
        "ir_skeleton": {
            "steps": [
                _step("search", "web.search", params={"query": "trending topic"}),
                _step("copy", "docx.generate", params={"template": "social_copy"}, depends_on=["search"]),
            ]
        },
        "required_permissions": ["chat:write"],
        "visibility": "tenant_public",
    },
    {
        "skill_id": "weekly_report",
        "name": "weekly_report",
        "description": "金线：上周热点 + 效能指标 → 社媒周报",
        "cot_template": (
            "1. 并行 hotspot.dig 与 analytics.summary（7d）\n"
            "2. 汇总为周报大纲\n"
            "3. docx.generate 输出周报"
        ),
        "ir_skeleton": {
            "steps": [
                _step("dig", "hotspot.dig", params={"window": "7d"}),
                _step("metrics", "analytics.summary", params={"metric": "engagement", "window": "7d"}),
                _step(
                    "report",
                    "docx.generate",
                    params={"template": "weekly_social_report"},
                    depends_on=["dig", "metrics"],
                ),
            ]
        },
        "required_permissions": ["chat:write", "analytics:read"],
        "visibility": "tenant_public",
    },
    {
        "skill_id": "skill_extract",
        "name": "skill_extract",
        "description": "半自动萃取：task_plan 轨迹 → draft skill_asset",
        "cot_template": (
            "1. 扫描 chat.task_plan 审计轨迹\n"
            "2. miner 归纳 CoT + ir_skeleton\n"
            "3. draft → 管理员审核 → publish 三关"
        ),
        "ir_skeleton": {
            "steps": [
                _step("plan", "plan.status", params={"run_id": "{{run_id}}"}),
                _step("metrics", "sys.metrics", params={"component": "skill_assets"}),
            ]
        },
        "required_permissions": ["chat:write", "admin:read"],
        "visibility": "tenant_public",
    },
]

BUILTIN_SKILL_IDS = frozenset(d["skill_id"] for d in BUILTIN_SKILL_ASSET_CATALOG)
