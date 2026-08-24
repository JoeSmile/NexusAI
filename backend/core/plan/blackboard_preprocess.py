"""Blackboard write conflict preprocessing (Task 61-s3 P1 / spec §7.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, Protocol


class _PrevEntry(Protocol):
    fact_content: str
    confidence: float
    document_ids_ref: list[str]
    version: int

PreprocessAction = Literal[
    "insert",
    "dedup_skip",
    "confidence_suppress",
    "homogeneous_merge",
    "semantic_conflict",
]


@dataclass(frozen=True)
class PreprocessResult:
    action: PreprocessAction
    fact_content: str | None = None
    confidence: float | None = None
    document_ids_ref: list[str] | None = None
    detail: str = ""


def _normalize_fact(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _numeric_tokens(text: str) -> list[str]:
    return re.findall(r"\d+", text or "")


def _facts_similar(a: str, b: str) -> bool:
    na, nb = _normalize_fact(a), _normalize_fact(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    nums_a, nums_b = _numeric_tokens(a), _numeric_tokens(b)
    if nums_a and nums_b and nums_a != nums_b:
        return False
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 8 and shorter in longer:
        return True
    compact_a, compact_b = na.replace(" ", ""), nb.replace(" ", "")
    if len(compact_a) >= 6 and len(compact_b) >= 6:
        short_c, long_c = (
            (compact_a, compact_b) if len(compact_a) <= len(compact_b) else (compact_b, compact_a)
        )
        if short_c in long_c:
            return True
        if SequenceMatcher(None, compact_a, compact_b).ratio() >= 0.78:
            return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / len(ta | tb)
    return overlap >= 0.85


def preprocess_blackboard_write(
    *,
    topic: str,
    fact_content: str,
    confidence: float,
    document_ids_ref: list[str],
    prev: _PrevEntry | None,
) -> PreprocessResult:
    """Machine-side dedup / suppress / merge before LLM conflict resolution."""
    fact = fact_content.strip()
    if prev is None:
        return PreprocessResult(
            action="insert",
            fact_content=fact,
            confidence=confidence,
            document_ids_ref=list(document_ids_ref),
        )

    prev_fact = prev.fact_content.strip()
    if prev_fact == fact:
        return PreprocessResult(action="dedup_skip", detail="identical_fact")

    if _facts_similar(prev_fact, fact):
        merged_docs = sorted(set(prev.document_ids_ref) | set(document_ids_ref))
        merged_conf = max(float(prev.confidence), float(confidence))
        merged_fact = prev_fact if len(prev_fact) >= len(fact) else fact
        return PreprocessResult(
            action="homogeneous_merge",
            fact_content=merged_fact,
            confidence=merged_conf,
            document_ids_ref=merged_docs,
            detail="similar_fact_merged",
        )

    if float(confidence) < float(prev.confidence) - 0.05:
        return PreprocessResult(
            action="confidence_suppress",
            detail=f"lower_confidence:{confidence:.2f}<{prev.confidence:.2f}",
        )

    return PreprocessResult(
        action="semantic_conflict",
        fact_content=fact,
        confidence=confidence,
        document_ids_ref=list(document_ids_ref),
        detail="semantic_mismatch",
    )
