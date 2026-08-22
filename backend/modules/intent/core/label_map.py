"""Product IntentType (7-class) alignment and legacy label normalization."""

from __future__ import annotations

from ..models.intent_models import IntentType

PRODUCT_INTENT_VALUES: frozenset[str] = frozenset(i.value for i in IntentType)

# FinGPT / Snips-style 12-class (intent_model_v2) → product 7-class
LEGACY_FINGPT_12_TO_PRODUCT: dict[str, str] = {
    "alarm": IntentType.FUNCTION.value,
    "calendar": IntentType.FUNCTION.value,
    "control": IntentType.FUNCTION.value,
    "email": IntentType.FUNCTION.value,
    "finance": IntentType.CONVERSATION.value,
    "funny": IntentType.CHAT.value,
    "music": IntentType.CHAT.value,
    "navigation": IntentType.FUNCTION.value,
    "qa": IntentType.KNOWLEDGE_QUERY.value,
    "shopping": IntentType.FUNCTION.value,
    "unknown": IntentType.CONVERSATION.value,
    "weather": IntentType.CHAT.value,
}

# Common aliases seen in seed exports / notebooks
LABEL_ALIASES: dict[str, str] = {
    "knowledge": IntentType.KNOWLEDGE_QUERY.value,
    "query": IntentType.KNOWLEDGE_QUERY.value,
    "greet": IntentType.GREETING.value,
    "small_talk": IntentType.CHAT.value,
    "smalltalk": IntentType.CHAT.value,
    "default": IntentType.CONVERSATION.value,
}


def normalize_label(raw: str | None) -> str:
    """Map arbitrary/legacy label to a product IntentType value."""
    if not raw or not str(raw).strip():
        return IntentType.CONVERSATION.value
    key = str(raw).strip().lower()
    if key in PRODUCT_INTENT_VALUES:
        return key
    if key in LEGACY_FINGPT_12_TO_PRODUCT:
        return LEGACY_FINGPT_12_TO_PRODUCT[key]
    if key in LABEL_ALIASES:
        return LABEL_ALIASES[key]
    return IntentType.CONVERSATION.value


def is_product_label(label: str) -> bool:
    return label in PRODUCT_INTENT_VALUES
