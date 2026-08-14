"""Task 42 S2 — T0 结构化条目规则抽取 + pending 绑定（零 LLM）。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.core.errors import ErrorCode
from backend.core.memory.extractor import _is_safe_fact, _slug
from backend.core.memory.types import (
    DecisionItem,
    EntityItem,
    EntityRelation,
    EntityType,
    ErrorCodeItem,
    MemoryItem,
    TodoItem,
    TodoOwnerKind,
)
from backend.core.memory.validators import (
    char_bigram_overlap,
    normalize_for_grounding,
    validate_item,
)

logger = logging.getLogger(__name__)

_PLATFORM_CODES = frozenset(e.value for e in ErrorCode)
_RE_ERROR = re.compile(r"\b([A-Z]+[-_]\d{3})\b")
_RE_DECISION = re.compile(
    r"(?:决定|拍板|采用|不采用)\s*(.{2,80})"
)
_RE_TODO = re.compile(
    r"(?:待办[:：]?|记得做|请记得)\s*(.{2,80})"
)
# 实体句式（Important 2A：宁缺勿滥；勿放宽后继字符类）
_RE_ENTITY = re.compile(
    r"(同事|客户|供应商)\s*([\u4e00-\u9fa5]{2,4})(?=\s|$|[，。！？、；：]|来|去|帮|评审|完成|负责)"
)
_RE_ENTITY_SYS = re.compile(
    r"(系统|项目)\s*([A-Za-z0-9\u4e00-\u9fa5]{2,12})"
)
_RE_PRONOUN = re.compile(r"(他|她|他们|她们)")
_STOP = frozenset("的了在是和与把被我你他她它".split())
_RELATION_MAP = {
    "同事": EntityRelation.COLLEAGUE,
    "客户": EntityRelation.CUSTOMER,
    "供应商": EntityRelation.SUPPLIER,
    "系统": EntityRelation.SYSTEM,
    "项目": EntityRelation.PROJECT,
}


@dataclass
class StructuredCandidate:
    item: MemoryItem
    key: str
    source_text: str


def extract_structured_items(user_message: str) -> list[StructuredCandidate]:
    """从用户句抽取四类候选（R4 显式句式）；不含代词 pending。"""
    text = (user_message or "").strip()
    if not text:
        return []
    out: list[StructuredCandidate] = []

    for m in list(_RE_ENTITY.finditer(text)) + list(_RE_ENTITY_SYS.finditer(text)):
        rel_raw, name = m.group(1), m.group(2).strip()
        if name in ("他", "她", "它") or not _is_safe_fact(name):
            continue
        if any(x in name for x in ("也", "都", "就", "还", "遇到")):
            continue
        rel = _RELATION_MAP.get(rel_raw, EntityRelation.UNKNOWN)
        span = m.group(0)
        et = (
            EntityType.PERSON
            if rel_raw in ("同事", "客户", "供应商")
            else (EntityType.PROJECT if rel_raw == "项目" else EntityType.SYSTEM)
        )
        item: MemoryItem = EntityItem(
            text=name,
            source_span=span,
            confidence=0.7,
            name=name,
            entity_type=et,
            relation=rel,
            mention_source="user",
        )
        out.append(
            StructuredCandidate(
                item=item, key=f"entity:{_slug(name)}", source_text=text
            )
        )

    for m in _RE_ERROR.finditer(text):
        raw = m.group(1)
        try:
            item = ErrorCodeItem(
                text=raw,
                source_span=raw,
                confidence=1.0 if raw.upper().replace("-", "_") in _PLATFORM_CODES else 0.9,
                code=raw,
                count=1,
            )
        except Exception:
            continue
        out.append(
            StructuredCandidate(
                item=item, key=f"error:{item.code}", source_text=text
            )
        )

    for m in _RE_DECISION.finditer(text):
        phrase = m.group(1).strip()
        if not _is_safe_fact(phrase):
            continue
        span = m.group(0)
        item = DecisionItem(
            text=phrase[:120],
            source_span=span[:200],
            confidence=0.8,
            statement=phrase[:200],
            chosen=phrase[:80],
        )
        out.append(
            StructuredCandidate(
                item=item, key=f"decision:{_slug(phrase)}", source_text=text
            )
        )

    for m in _RE_TODO.finditer(text):
        action = m.group(1).strip()
        if not action or not _is_safe_fact(action):
            continue
        owner_kind = TodoOwnerKind.SELF
        owner = None
        em = _RE_ENTITY.search(action) or _RE_ENTITY.search(text)
        if em and em.group(2) not in ("他", "她"):
            owner_kind = TodoOwnerKind.ENTITY
            owner = em.group(2).strip()
        due = None
        dm = re.search(r"(周五前|下周二前|\d{4}-\d{2}-\d{2})", text)
        if dm:
            due = dm.group(1)
        item = TodoItem(
            text=action[:120],
            source_span=m.group(0)[:200],
            confidence=0.75,
            action=action[:200],
            owner=owner,
            owner_kind=owner_kind,
            due=due,
            status="open",
        )
        slug = _slug(action)
        out.append(
            StructuredCandidate(
                item=item, key=f"todo:{slug}", source_text=text
            )
        )

    # R7 order: entity → error → decision → todo
    order = {"entity": 0, "error_code": 1, "decision": 2, "todo": 3}
    out.sort(key=lambda c: order.get(c.item.type, 9))
    return out


def pronoun_hits(user_message: str) -> list[str]:
    return list(dict.fromkeys(_RE_PRONOUN.findall(user_message or "")))


def pending_key(session_id: str, antecedent: str) -> str:
    return f"pending:{session_id}:{_slug(antecedent)}"


def pending_value(
    *,
    antecedent: str,
    context_snippet: str,
    user_turn_at_create: int,
    first_mention_ts: str | None = None,
) -> str:
    now = datetime.now(UTC).isoformat()
    return json.dumps(
        {
            "antecedent": antecedent,
            "context_snippet": (context_snippet or "")[:80],
            "first_mention_ts": first_mention_ts or now,
            "last_mention_ts": now,
            "user_turn_at_create": user_turn_at_create,
            "bound_entity": None,
        },
        ensure_ascii=False,
    )


def _shared_content_token(a: str, b: str) -> bool:
    na, nb = normalize_for_grounding(a), normalize_for_grounding(b)
    # length>=2 substrings excluding stop chars
    tokens: set[str] = set()
    for i in range(len(na) - 1):
        tok = na[i : i + 2]
        if any(c in _STOP for c in tok):
            continue
        tokens.add(tok)
    for i in range(len(nb) - 1):
        tok = nb[i : i + 2]
        if tok in tokens:
            return True
    return False


def context_overlap_ok(turn: str, snippet: str) -> bool:
    """R1.1 条件 4。"""
    nt, ns = normalize_for_grounding(turn), normalize_for_grounding(snippet)
    if char_bigram_overlap(nt, ns) >= 0.4:
        return True
    return _shared_content_token(turn, snippet)


def should_bind_pending(
    *,
    session_id: str,
    pending_key_str: str,
    pending_payload: dict[str, Any],
    explicit_name: str,
    explicit_turn: str,
    current_user_turns: int,
) -> bool:
    """R1.1 五条件（一对一由调用方在候选列表上取最新）。"""
    # 1 same session
    prefix = f"pending:{session_id}:"
    if not pending_key_str.startswith(prefix):
        return False
    # 2 explicit name non-empty (caller ensures R4 entity)
    if not explicit_name or explicit_name in ("他", "她"):
        return False
    # 3 turn window
    created = int(pending_payload.get("user_turn_at_create") or 0)
    if current_user_turns - created > 8:
        return False
    # 4 overlap
    snippet = str(pending_payload.get("context_snippet") or "")
    if not context_overlap_ok(explicit_turn, snippet):
        return False
    return True


def pick_latest_pending(
    candidates: list[tuple[str, dict[str, Any]]],
) -> tuple[str, dict[str, Any]] | None:
    if not candidates:
        return None

    def _ts(p: dict[str, Any]) -> str:
        return str(p.get("last_mention_ts") or p.get("first_mention_ts") or "")

    return max(candidates, key=lambda kv: _ts(kv[1]))


def validate_and_reason(
    item: MemoryItem,
    source_text: str,
    *,
    known_entity_names: set[str] | None = None,
) -> tuple[bool, str | None]:
    return validate_item(item, source_text, known_entity_names=known_entity_names)
