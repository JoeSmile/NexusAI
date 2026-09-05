"""Conservative complex-task detector (Task 88 A1).

拿不准 → 确定性路径（不规划）。明确工具/生成/检索意图或强模式词才规划。
"""

from __future__ import annotations

import re

from packages.pipeline.intent_path import short_path_predicate

COMPLEX_INTENTS = frozenset(
    {
        "content_creation",
        "content_analysis",
        "knowledge_query",
        "function",
    }
)
COMPLEX_INTENT_MIN_CONF = 0.5

_PATTERN = re.compile(
    r"帮我(写|分析|对比|规划|整理|查)|"
    r"对比.+和|"
    r"分析一下|分析下|"
    r"口播|热点挖掘|知识库|"
    r"生成一篇|写个周报|写周报"
)


def is_complex_task(state: dict) -> bool:
    if short_path_predicate(state):
        return False
    intent = str(state.get("intent") or "")
    try:
        conf = float(state.get("intent_confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if intent in COMPLEX_INTENTS and conf >= COMPLEX_INTENT_MIN_CONF:
        return True
    text = str(state.get("message") or state.get("raw_input") or "")
    return bool(_PATTERN.search(text))
