"""Intent-conditioned slot schemas for L0 entity extraction (rule MVP)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotDef:
    name: str
    required: bool = False
    patterns: tuple[str, ...] = ()
    keywords: tuple[tuple[str, str], ...] = ()


ENTITY_SCHEMAS: dict[str, list[SlotDef]] = {
    "after_sales": [
        SlotDef(
            "order_id",
            patterns=(
                r"(?:订单(?:号)?|单号)[#:：\s]*([A-Za-z0-9\-]{6,20})",
            ),
        ),
        SlotDef(
            "reason",
            keywords=(
                ("质量问题", "质量问题"),
                ("不想要", "七天无理由"),
                ("七天无理由", "七天无理由"),
            ),
        ),
        SlotDef(
            "issue_type",
            keywords=(
                ("退款", "退款"),
                ("退货", "退货"),
                ("投诉", "投诉"),
                ("发票", "发票"),
                ("换货", "换货"),
            ),
        ),
        SlotDef(
            "topic",
            keywords=(
                ("投诉", "服务投诉"),
                ("差评", "差评投诉"),
            ),
        ),
    ],
    "pre_sales": [
        SlotDef(
            "sku",
            patterns=(r"(标准版|专业版|企业版)",),
        ),
        SlotDef(
            "quantity",
            patterns=(r"(\d+)\s*(?:套|个|台|份)",),
        ),
        SlotDef(
            "product_scope",
            patterns=(
                r"(?:了解|咨询|介绍)(.{2,30}?)(?:方案|产品|价格)",
            ),
        ),
    ],
    "content_creation": [
        SlotDef(
            "topic",
            patterns=(
                r"(?:关于|针对)(.{2,40}?)(?:的)?(?:脚本|文案|口播)",
            ),
        ),
        SlotDef(
            "theme",
            patterns=(r"(?:主题|话题)[：:]\s*(.{2,30})",),
        ),
        SlotDef(
            "window",
            keywords=(
                ("本周", "7d"),
                ("上周", "7d"),
                ("本月", "30d"),
            ),
        ),
    ],
    "content_analysis": [
        SlotDef(
            "topic",
            patterns=(r"(?:分析|评估)(.{2,40}?)(?:内容|竞品|热点)",),
        ),
    ],
    "knowledge_query": [
        SlotDef(
            "object",
            patterns=(
                r"(?:查询|了解|查一下)(.{2,30}?)(?:制度|流程|政策|在哪)",
                r"(?:如何|怎么)(.{2,30}?)(?:制度|流程|政策)",
            ),
        ),
    ],
    "function": [
        SlotDef(
            "time",
            patterns=(
                r"(今天|明天|后天|\d{1,2}月\d{1,2}[日号])",
            ),
        ),
        SlotDef(
            "action",
            keywords=(
                ("提醒", "提醒"),
                ("备忘", "备忘"),
                ("记得", "提醒"),
            ),
        ),
    ],
}
