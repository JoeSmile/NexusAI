"""Task 42 S4 — 抽取飞轮埋点（只采集，不自动升级策略）。"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_RE_CORRECTION = re.compile(
    r"(?:不是|错了|改成)\s*(.+?)\s*(?:是|为|改成)\s*(.+)"
)

# 进程内计数（测试可 reset；生产指标另打 LangFuse）
_stats: Counter[str] = Counter()
_golden_candidates: list[dict[str, Any]] = []


@dataclass
class ExtractionTelemetry:
    accepts: int = 0
    rejects: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepts": self.accepts,
            "rejects": dict(self.rejects),
        }


def reset_flywheel_for_tests() -> None:
    _stats.clear()
    _golden_candidates.clear()


def record_item_outcome(
    *,
    accepted: bool,
    reason_code: str | None = None,
    item_type: str | None = None,
) -> None:
    if accepted:
        _stats["accept"] += 1
        if item_type:
            _stats[f"accept:{item_type}"] += 1
    else:
        code = reason_code or "REJECT_UNKNOWN"
        _stats["reject"] += 1
        _stats[f"reject:{code}"] += 1
    _emit_langfuse_scores()


def record_correction_phrase(user_message: str) -> dict[str, str] | None:
    """识别纠正句式 → 只积累 golden 候选，不改策略。"""
    m = _RE_CORRECTION.search(user_message or "")
    if not m:
        return None
    cand = {"wrong": m.group(1).strip()[:80], "right": m.group(2).strip()[:80]}
    _golden_candidates.append(cand)
    _stats["correction"] += 1
    return cand


def record_repeat_ask(signal: bool = True) -> None:
    if signal:
        _stats["repeat_ask"] += 1


def flywheel_snapshot() -> dict[str, Any]:
    return {
        "counts": dict(_stats),
        "golden_candidates": list(_golden_candidates),
    }


def _emit_langfuse_scores() -> None:
    try:
        from packages.observability.decorators import langfuse_context

        langfuse_context.update_current_observation(
            metadata={
                "memory_extraction": {
                    "accept": _stats.get("accept", 0),
                    "reject": _stats.get("reject", 0),
                    "correction": _stats.get("correction", 0),
                    "repeat_ask": _stats.get("repeat_ask", 0),
                }
            }
        )
    except Exception:
        logger.debug("memory flywheel langfuse score skipped", exc_info=True)
