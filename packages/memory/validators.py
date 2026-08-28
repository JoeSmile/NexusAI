"""Task 42 — T2 校验链（纯规则，零 LLM）。"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

from backend.core.errors import ErrorCode
from packages.guardrails.pii_patterns import PII_PATTERNS
from packages.memory.extractor import _UNSAFE_FACT
from packages.memory.types import (
    DecisionItem,
    EntityItem,
    EntityRelation,
    ErrorCodeItem,
    MemoryItem,
    TodoItem,
    TodoOwnerKind,
    parse_memory_item,
)

REJECT_SCHEMA = "REJECT_SCHEMA"
REJECT_GROUNDING = "REJECT_GROUNDING"
REJECT_SECURITY = "REJECT_SECURITY"
REJECT_SEMANTIC = "REJECT_SEMANTIC"

_PLATFORM_CODES = frozenset(e.value for e in ErrorCode)


def grounding_min_overlap() -> float:
    try:
        return float(os.getenv("GROUNDING_MIN_OVERLAP", "0.6"))
    except ValueError:
        return 0.6


def normalize_for_grounding(text: str) -> str:
    """全角→半角、去标点空白、小写（R3）。"""
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        # 全角空格与常见全角标点
        code = ord(ch)
        if code == 0x3000:
            continue
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("Z") or ch.isspace():
            continue
        out.append(ch.lower())
    return "".join(out)


def char_bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def char_bigram_overlap(a: str, b: str) -> float:
    ga, gb = char_bigrams(a), char_bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga)


def schema_validator(item: Any) -> tuple[bool, str | None]:
    try:
        if isinstance(item, MemoryItem):
            # 已是模型：再校验一次字典往返
            parse_memory_item(item.model_dump())
            return True, None
        if isinstance(item, dict):
            parse_memory_item(item)
            return True, None
        return False, REJECT_SCHEMA
    except Exception:
        return False, REJECT_SCHEMA


def grounding_validator(item: MemoryItem, source_text: str) -> tuple[bool, str | None]:
    span = item.source_span or ""
    src = source_text or ""
    n_span = normalize_for_grounding(span)
    n_src = normalize_for_grounding(src)
    if not n_span or not n_src:
        return False, REJECT_GROUNDING
    # span 原文长度（规范化前）< 4 → 必须子串
    if len(normalize_for_grounding(span)) < 4 or len(span.strip()) < 4:
        if n_span not in n_src:
            return False, REJECT_GROUNDING
        return True, None
    if n_span in n_src:
        return True, None
    if char_bigram_overlap(n_span, n_src) >= grounding_min_overlap():
        return True, None
    return False, REJECT_GROUNDING


def _has_pii(text: str) -> bool:
    for pat in PII_PATTERNS.values():
        if re.search(pat, text or ""):
            return True
    return False


def security_validator(item: MemoryItem, source_text: str | None = None) -> tuple[bool, str | None]:
    """扫 item 字段；不扫整段原文（Task 42 Important 1A 落档）。

    避免叙述里的「密钥」误杀合法 error 条目（如「失败返回 AUTH_001 无效密钥」）。
    """
    del source_text
    blobs = [item.text, item.source_span]
    if isinstance(item, EntityItem):
        blobs.append(item.name)
    if isinstance(item, ErrorCodeItem):
        blobs.extend([item.code, item.message or ""])
    if isinstance(item, DecisionItem):
        blobs.append(item.statement)
    if isinstance(item, TodoItem):
        blobs.extend([item.action, item.owner or ""])
    for b in blobs:
        if not b:
            continue
        if _UNSAFE_FACT.search(b):
            return False, REJECT_SECURITY
        if _has_pii(b):
            return False, REJECT_SECURITY
    return True, None


def semantic_validator(
    item: MemoryItem,
    *,
    known_entity_names: set[str] | None = None,
) -> tuple[bool, str | None]:
    known = known_entity_names or set()
    if isinstance(item, EntityItem):
        if item.relation not in EntityRelation:
            return False, REJECT_SEMANTIC
        return True, None
    if isinstance(item, ErrorCodeItem):
        # 平台白名单或外部格式（已在 schema 过 regex）
        if item.code in _PLATFORM_CODES:
            return True, None
        # 外部：已过 ERROR_CODE_RE；拒绝过长或含小写（schema 已 upper）
        if len(item.code) > 24:
            return False, REJECT_SEMANTIC
        return True, None
    if isinstance(item, DecisionItem):
        if not item.statement or len(item.statement) < 2:
            return False, REJECT_SEMANTIC
        for name in item.related:
            if name and name not in known:
                # related 引用未知名 → 语义拒（可在 S2 先落 entity）
                return False, REJECT_SEMANTIC
        return True, None
    if isinstance(item, TodoItem):
        if item.owner_kind == TodoOwnerKind.SELF:
            return True, None
        owner = (item.owner or "").strip()
        if not owner:
            return False, REJECT_SEMANTIC
        # 代词未绑定
        if owner in ("他", "她", "它", "他们", "她们"):
            return False, REJECT_SEMANTIC
        if owner not in known:
            return False, REJECT_SEMANTIC
        return True, None
    return False, REJECT_SEMANTIC


def validate_item(
    item: MemoryItem | dict[str, Any],
    source_text: str,
    *,
    known_entity_names: set[str] | None = None,
) -> tuple[bool, str | None]:
    """四 validator 顺序执行；任一 fail → (False, REJECT_*)。"""
    ok, reason = schema_validator(item)
    if not ok:
        return False, reason or REJECT_SCHEMA
    parsed: MemoryItem
    if isinstance(item, dict):
        try:
            parsed = parse_memory_item(item)
        except Exception:
            return False, REJECT_SCHEMA
    else:
        parsed = item

    ok, reason = grounding_validator(parsed, source_text)
    if not ok:
        return False, reason
    ok, reason = security_validator(parsed, source_text)
    if not ok:
        return False, reason
    ok, reason = semantic_validator(parsed, known_entity_names=known_entity_names)
    if not ok:
        return False, reason
    return True, None
