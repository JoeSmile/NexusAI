"""Shared text normalization for chat exact cache + RAG (Task 39).

NFKC + lower + whitespace fold + strip. No synonym rewrite.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_text(text: str) -> str:
    """Light lossless normalize: NFKC + lower + collapse whitespace."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def make_normalized_query_hash(text: str) -> str:
    """SHA256 of normalized text, first 16 hex chars (exact cache key suffix)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]
