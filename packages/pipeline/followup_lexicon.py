"""Shared follow-up / deixis lexicon for exact bypass (Task 76.0) and funnel L1 (77)."""

from __future__ import annotations

import re

from packages.text_normalize import normalize_text

# Full-utterance match only — never substring (「对」≠「对冲基金」).
FOLLOWUP_UTTERANCES: frozenset[str] = frozenset(
    {
        "继续",
        "然后呢",
        "嗯",
        "好的",
        "是的",
        "对",
        "接着说",
        "还有呢",
        "后来呢",
        "那然后",
        "明天呢",
        # 同等短指代
        "嗯嗯",
        "那个呢",
        "这个呢",
        "继续说",
        "然后",
        "接着",
    }
)

_EDGE_PUNCT = re.compile(
    r"^[\s。！？!?.,，、~～…·「」『』\"'“”]+|[\s。！？!?.,，、~～…·「」『』\"'“”]+$"
)


def canonicalize_followup(text: str) -> str:
    """Normalize then strip edge punctuation so 「明天呢？」 hits the lexicon."""
    s = normalize_text(text or "")
    if not s:
        return ""
    prev = None
    while prev != s:
        prev = s
        s = _EDGE_PUNCT.sub("", s)
    return s


def is_followup_utterance(text: str) -> bool:
    """True when the whole (normalized) message is a short follow-up / deixis."""
    return canonicalize_followup(text) in FOLLOWUP_UTTERANCES
