"""Product IntentType (8-class) alignment and legacy label normalization."""

from __future__ import annotations

from ..models.intent_models import IntentType

PRODUCT_INTENT_VALUES: frozenset[str] = frozenset(i.value for i in IntentType)

# v8 training id2label order (must match models/intent_model_v8/model/config.json)
V8_ID2LABEL: dict[int, str] = {
    0: IntentType.GREETING.value,
    1: IntentType.PRE_SALES.value,
    2: IntentType.AFTER_SALES.value,
    3: IntentType.CONTENT_CREATION.value,
    4: IntentType.CONTENT_ANALYSIS.value,
    5: IntentType.KNOWLEDGE_QUERY.value,
    6: IntentType.FUNCTION.value,
    7: IntentType.CONVERSATION.value,
}
V8_LABEL_ORDER: tuple[str, ...] = tuple(V8_ID2LABEL[i] for i in range(len(V8_ID2LABEL)))

# FinGPT / Snips-style 12-class → product 8-class
LEGACY_FINGPT_12_TO_PRODUCT: dict[str, str] = {
    "alarm": IntentType.FUNCTION.value,
    "calendar": IntentType.FUNCTION.value,
    "control": IntentType.FUNCTION.value,
    "email": IntentType.FUNCTION.value,
    "finance": IntentType.CONVERSATION.value,
    "funny": IntentType.CONVERSATION.value,
    "music": IntentType.CONVERSATION.value,
    "navigation": IntentType.FUNCTION.value,
    "qa": IntentType.KNOWLEDGE_QUERY.value,
    "shopping": IntentType.PRE_SALES.value,
    "unknown": IntentType.CONVERSATION.value,
    "weather": IntentType.CONVERSATION.value,
}

# Legacy product 7-class → 8-class (crisis/chat/advice need text-aware split)
LEGACY_PRODUCT_7_TO_8: dict[str, str] = {
    "crisis": IntentType.CONVERSATION.value,
    "chat": IntentType.CONVERSATION.value,
    "greeting": IntentType.GREETING.value,
    "knowledge_query": IntentType.KNOWLEDGE_QUERY.value,
    "function": IntentType.FUNCTION.value,
    "conversation": IntentType.CONVERSATION.value,
}

# Common aliases
LABEL_ALIASES: dict[str, str] = {
    "knowledge": IntentType.KNOWLEDGE_QUERY.value,
    "query": IntentType.KNOWLEDGE_QUERY.value,
    "greet": IntentType.GREETING.value,
    "small_talk": IntentType.CONVERSATION.value,
    "smalltalk": IntentType.CONVERSATION.value,
    "default": IntentType.CONVERSATION.value,
    "chat": IntentType.CONVERSATION.value,
    "crisis": IntentType.CONVERSATION.value,
    "advice": IntentType.CONVERSATION.value,
    "sales": IntentType.PRE_SALES.value,
    "quote": IntentType.PRE_SALES.value,
    "refund": IntentType.AFTER_SALES.value,
    "customer_service": IntentType.AFTER_SALES.value,
    "complaint": IntentType.AFTER_SALES.value,
    "escalation": IntentType.AFTER_SALES.value,
    "hotspot": IntentType.CONTENT_ANALYSIS.value,
    "content": IntentType.CONTENT_CREATION.value,
    "copywriting": IntentType.CONTENT_CREATION.value,
    "social": IntentType.CONTENT_CREATION.value,
    "weekly_report": IntentType.CONTENT_CREATION.value,
    "report": IntentType.CONTENT_CREATION.value,
}

_PRE_SALES_HINTS = (
    "产品", "报价", "报个价", "方案", "售前", "介绍", "对比", "公司介绍", "sku", "演示",
)
_AFTER_SALES_HINTS = (
    "退款", "退货", "投诉", "发票", "故障", "售后", "换货", "维修", "工单",
)
_CONTENT_ANALYSIS_HINTS = (
    "分析", "评估", "竞品分析", "热点", "选题", "洞察", "数据", "爆不爆", "趋势", "竞争对手",
)
_CONTENT_CREATION_HINTS = (
    "口播", "脚本", "文案", "周报", "创作", "生成", "写个", "社媒", "短视频",
    "写", "推文", "软文", "笔记", "稿", "邀请函", "公告", "总结", "纪要",
)
_CONTENT_ANALYSIS_HINTS_EXTRA = (
    "梳理", "热点", "选题", "挖掘", "洞察", "调研", "复盘",
)
_KNOWLEDGE_TO_AFTER_SALES_HINTS = (
    "密码", "账号", "登录", "发票", "报销", "退款", "投诉", "报错", "it", "支持",
    "故障", "工单", "到期", "续费", "验证码", "手机号", "席位", "存储", "数据导出",
    "扣费", "订阅",
)
_FAREWELL_HINTS = ("再见", "拜拜", "回见")


def split_legacy_advice(text: str) -> str:
    """Rough-split old advice labels into business 8-class (Task 65 slice 8)."""
    t = (text or "").lower()
    if any(h in t for h in _PRE_SALES_HINTS):
        return IntentType.PRE_SALES.value
    if any(h in t for h in _AFTER_SALES_HINTS):
        return IntentType.AFTER_SALES.value
    if any(h in t for h in _CONTENT_ANALYSIS_HINTS):
        return IntentType.CONTENT_ANALYSIS.value
    if any(h in t for h in _CONTENT_CREATION_HINTS):
        return IntentType.CONTENT_CREATION.value
    return IntentType.CONVERSATION.value


def split_legacy_function(text: str) -> str:
    t = (text or "").lower()
    if any(h in t for h in _CONTENT_CREATION_HINTS):
        return IntentType.CONTENT_CREATION.value
    if any(h in t for h in _CONTENT_ANALYSIS_HINTS) or any(
        h in t for h in _CONTENT_ANALYSIS_HINTS_EXTRA
    ):
        return IntentType.CONTENT_ANALYSIS.value
    return IntentType.FUNCTION.value


def apply_semantic_migration(label: str, text: str | None) -> str:
    """v8.3 text-aware relabel (aligned with intent_project/prepare_v8.py)."""
    if not text:
        return label
    t = text.lower()
    if label == IntentType.GREETING.value:
        if any(h in t for h in _FAREWELL_HINTS):
            return IntentType.CONVERSATION.value
        return label
    if label == IntentType.FUNCTION.value:
        return split_legacy_function(text)
    if label == IntentType.KNOWLEDGE_QUERY.value:
        if any(h in t for h in _KNOWLEDGE_TO_AFTER_SALES_HINTS):
            return IntentType.AFTER_SALES.value
        return label
    if label == IntentType.CONVERSATION.value:
        if "在吗" in t:
            return IntentType.GREETING.value
        return label
    return label


def normalize_label(raw: str | None, *, text: str | None = None) -> str:
    """Map arbitrary/legacy label to a product IntentType value."""
    if not raw or not str(raw).strip():
        return IntentType.CONVERSATION.value
    key = str(raw).strip().lower()
    if key == "advice" and text:
        return split_legacy_advice(text)
    if key == "function" and text:
        return split_legacy_function(text)
    if key in PRODUCT_INTENT_VALUES:
        return apply_semantic_migration(key, text)
    if key in LEGACY_PRODUCT_7_TO_8:
        return LEGACY_PRODUCT_7_TO_8[key]
    if key in LEGACY_FINGPT_12_TO_PRODUCT:
        return LEGACY_FINGPT_12_TO_PRODUCT[key]
    if key in LABEL_ALIASES:
        mapped = LABEL_ALIASES[key]
        if mapped == IntentType.CONVERSATION.value and key == "advice" and text:
            return split_legacy_advice(text)
        return mapped
    return IntentType.CONVERSATION.value


def normalize_sample(text: str, label: str | None) -> str:
    """Normalize one training row (label + text for advice/function splits)."""
    return normalize_label(label, text=text)


def is_product_label(label: str) -> bool:
    return label in PRODUCT_INTENT_VALUES
