"""BM25 lexical index for tool metadata (Task 60)."""

from __future__ import annotations

import math
import re
from collections import Counter

import jieba

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

# BM25 hyper-parameters (Okapi defaults)
_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    raw = (text or "").strip().lower()
    if not raw:
        return []
    try:
        parts = jieba.lcut_for_search(raw)
    except Exception:
        parts = _TOKEN_RE.findall(raw)
    out: list[str] = []
    for p in parts:
        t = p.strip().lower()
        if len(t) >= 2:
            out.append(t)
    return out or _TOKEN_RE.findall(raw)


class BM25Index:
    """In-memory BM25 over tool documents keyed by capability id."""

    def __init__(self) -> None:
        self._docs: dict[str, list[str]] = {}
        self._doc_len: dict[str, int] = {}
        self._df: Counter[str] = Counter()
        self._avgdl = 0.0

    def clear(self) -> None:
        self._docs.clear()
        self._doc_len.clear()
        self._df.clear()
        self._avgdl = 0.0

    def upsert(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        if doc_id in self._docs:
            for tok in set(self._docs[doc_id]):
                self._df[tok] -= 1
                if self._df[tok] <= 0:
                    del self._df[tok]
        self._docs[doc_id] = tokens
        self._doc_len[doc_id] = len(tokens)
        for tok in set(tokens):
            self._df[tok] += 1
        total = sum(self._doc_len.values())
        self._avgdl = total / max(len(self._doc_len), 1)

    def remove(self, doc_id: str) -> None:
        if doc_id not in self._docs:
            return
        for tok in set(self._docs[doc_id]):
            self._df[tok] -= 1
            if self._df[tok] <= 0:
                del self._df[tok]
        del self._docs[doc_id]
        del self._doc_len[doc_id]
        total = sum(self._doc_len.values())
        self._avgdl = total / max(len(self._doc_len), 1)

    def search(self, query: str, *, top_k: int = 20) -> list[tuple[str, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self._docs:
            return []
        n = len(self._docs)
        scores: list[tuple[str, float]] = []
        for doc_id, doc_tokens in self._docs.items():
            if not doc_tokens:
                continue
            tf = Counter(doc_tokens)
            dl = self._doc_len[doc_id]
            score = 0.0
            for term in q_tokens:
                if term not in tf:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                freq = tf[term]
                denom = freq + _K1 * (1 - _B + _B * dl / (self._avgdl or 1.0))
                score += idf * (freq * (_K1 + 1)) / (denom or 1.0)
            if score > 0:
                scores.append((doc_id, score))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[: max(1, top_k)]
