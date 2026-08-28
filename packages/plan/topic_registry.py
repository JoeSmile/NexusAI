"""Blackboard topic registry — core enum + prefix whitelist (Task 61-s3 P1 / spec §7.3)."""

from __future__ import annotations

CORE_TOPICS = frozenset(
    {
        "fact.general",
        "slots.missing",
        "slots.filled",
    }
)

PREFIX_WHITELIST = (
    "step.",
    "summary.",
    "pre_sales.",
    "after_sales.",
    "retrieval.",
    "slots.",
    "normalized.",
    "coref.",
    "request.",
    "fact.",
    "risk.",
)


class TopicRegistryError(ValueError):
    """Topic not in controlled registry."""


def normalize_topic(topic: str) -> str:
    raw = (topic or "fact.general").strip()
    return raw or "fact.general"


def topic_allowed(topic: str) -> bool:
    t = normalize_topic(topic)
    if t in CORE_TOPICS:
        return True
    return any(t.startswith(p) for p in PREFIX_WHITELIST)


def validate_topic(topic: str) -> str:
    """Return normalized topic or raise if not in registry."""
    t = normalize_topic(topic)
    if topic_allowed(t):
        return t
    raise TopicRegistryError(f"blackboard_topic_not_registered:{t}")


def match_topic_prefix(topic: str, filter_topic: str | None) -> bool:
    """filter_topic exact or prefix match (summary. → summary.weekly)."""
    if not filter_topic:
        return True
    ft = filter_topic.strip()
    if not ft:
        return True
    return topic == ft or topic.startswith(ft)
