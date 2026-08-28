"""AgentType registry — governance layer for sub-agent spawn (Task 62 / spec 2026-08-22)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TOPIC_SLOTS_MISSING = "slots.missing"
TOPIC_SLOTS_FILLED = "slots.filled"


class BlackboardPolicy(BaseModel):
    write_topics: list[str] | None = None
    read_scope: Literal["own", "all", "none"] = "all"
    min_read_confidence: float = 0.3
    conflict_resolution: Literal["confidence", "flag"] = "flag"


class AgentType(BaseModel):
    type_id: str
    role: str
    description: str
    capability_ids: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=lambda: ["chat:write"])
    risk_level: Literal["low", "medium", "high"] = "low"
    blackboard: BlackboardPolicy = Field(default_factory=BlackboardPolicy)
    required_slots: dict[str, str] = Field(default_factory=dict)
    max_steps: int = 10
    timeout_s: int = 120
    intent_tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


_BUILTIN: dict[str, AgentType] = {
    "pre_sales_agent": AgentType(
        type_id="pre_sales_agent",
        role="售前顾问",
        description="产品介绍、方案对比、报价与演示咨询",
        capability_ids=["rag.search", "rag-ask", "docx.generate", "im.notify"],
        permissions=["chat:write", "kb:read"],
        risk_level="low",
        blackboard=BlackboardPolicy(
            write_topics=["pre_sales.", "summary."],
            read_scope="all",
        ),
        required_slots={
            "product_scope": "想了解的产品或方案范围",
        },
        intent_tags=["pre_sales"],
    ),
    "after_sales_agent": AgentType(
        type_id="after_sales_agent",
        role="售后客服",
        description="退款、投诉、发票与故障工单处理",
        capability_ids=["im.notify", "memory.search", "mail.draft"],
        permissions=["chat:write"],
        risk_level="low",
        blackboard=BlackboardPolicy(
            write_topics=["after_sales.", "summary."],
            read_scope="all",
        ),
        required_slots={
            "issue_type": "问题类型（退款/投诉/发票/故障）",
        },
        intent_tags=["after_sales"],
    ),
    "content_agent": AgentType(
        type_id="content_agent",
        role="内容创作",
        description="口播脚本、社媒文案、周报等内容生成",
        capability_ids=["hotspot.dig", "docx.generate"],
        permissions=["chat:write"],
        intent_tags=["content_creation"],
    ),
    "analysis_agent": AgentType(
        type_id="analysis_agent",
        role="内容分析",
        description="热点挖掘、选题与竞品洞察",
        capability_ids=["hotspot.dig", "analytics.summary"],
        permissions=["chat:write"],
        intent_tags=["content_analysis"],
    ),
    "retriever_agent": AgentType(
        type_id="retriever_agent",
        role="知识检索",
        description="企业制度与知识库 RAG 问答",
        capability_ids=["rag.search", "rag-ask"],
        permissions=["chat:write", "kb:read"],
        intent_tags=["knowledge_query"],
    ),
    "function_executor": AgentType(
        type_id="function_executor",
        role="工具执行",
        description="提醒、日程、邮件等工具型任务",
        capability_ids=["calendar.query", "calendar.create", "im.notify", "mail.draft"],
        permissions=["chat:write"],
        intent_tags=["function"],
    ),
}


def get_agent_type(type_id: str) -> AgentType | None:
    return _BUILTIN.get(type_id)


def list_agent_types() -> list[AgentType]:
    return list(_BUILTIN.values())


def agent_type_for_intent(intent: str | None) -> AgentType | None:
    if not intent:
        return None
    key = str(intent).strip().lower()
    for at in _BUILTIN.values():
        if key in at.intent_tags:
            return at
    return None
