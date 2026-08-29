"""同主题 supersede — Task 41 S2b（P0-10）。

判定（写死）：同域 +（归一化 slug 相同 **或** 字符 2-gram Jaccard ≥ 0.8）。
禁向量近邻。无 status 列 → 直接删除旧 key（表已定型）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_RE_STRIP = re.compile(r"[，。！？、\s:：\-_/]+")
_USER_DOMAIN_PREFIXES = ("fact:", "preference:", "identity:")
_BIGRAM_THRESHOLD = 0.8


def normalize_slug(text: str) -> str:
    return _RE_STRIP.sub("", (text or "").lower())


def bigram_jaccard(a: str, b: str) -> float:
    def grams(s: str) -> set[str]:
        s = normalize_slug(s)
        if len(s) < 2:
            return {s} if s else set()
        return {s[i : i + 2] for i in range(len(s) - 1)}

    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def domain_of(key: str) -> str:
    return key.split(":", 1)[0] if ":" in (key or "") else ""


def same_topic(key_a: str, val_a: str, key_b: str, val_b: str) -> bool:
    """同域且（slug 归一化相等或 2-gram≥0.8）。"""
    if domain_of(key_a) != domain_of(key_b):
        return False
    if not key_a.startswith(_USER_DOMAIN_PREFIXES):
        return False
    slug_a = key_a.split(":", 1)[-1]
    slug_b = key_b.split(":", 1)[-1]
    if normalize_slug(slug_a) == normalize_slug(slug_b):
        return True
    if bigram_jaccard(slug_a, slug_b) >= _BIGRAM_THRESHOLD:
        return True
    if bigram_jaccard(str(val_a), str(val_b)) >= _BIGRAM_THRESHOLD:
        return True
    return False


def find_superseded_keys(
    *,
    existing: list[tuple[str, str]],
    new_key: str,
    new_value: str,
) -> list[str]:
    """Return keys (≠ new_key) that should be deleted before writing new_key."""
    out: list[str] = []
    for key, val in existing:
        if key == new_key:
            continue
        if same_topic(new_key, new_value, key, val):
            out.append(key)
    return out


FORGOTTEN_MARKER_KEY = "__forgotten__"


def supersede_user_domain(
    *,
    tenant_id: str,
    user_id: str,
    new_key: str,
    new_value: str,
    session: Any | None = None,
    commit: bool = True,
) -> list[str]:
    """删除同主题旧 warm 行；返回已删 key 列表。

    ``session`` 传入时复用调用方事务（与 upsert 同提交，防删后写失败丢记忆）。
    """
    if not new_key.startswith(_USER_DOMAIN_PREFIXES):
        return []
    from packages.database.pgvector_session import UserMemory, get_pg_session

    own_session = session is None
    if own_session:
        session_factory = get_pg_session()
        session = session_factory.Session()
    assert session is not None
    deleted: list[str] = []
    try:
        prefix = domain_of(new_key) + ":"
        rows = (
            session.query(UserMemory)
            .filter_by(tenant_id=tenant_id, user_id=user_id)
            .filter(UserMemory.key.like(f"{prefix}%"))
            .all()
        )
        existing = [(r.key, r.value) for r in rows]
        doomed = find_superseded_keys(
            existing=existing, new_key=new_key, new_value=new_value
        )
        for key in doomed:
            session.query(UserMemory).filter_by(
                tenant_id=tenant_id, user_id=user_id, key=key
            ).delete(synchronize_session=False)
            deleted.append(key)
        if deleted and commit and own_session:
            session.commit()
            logger.info(
                "supersede tid=%s uid=%s new=%s deleted=%s",
                tenant_id,
                user_id,
                new_key,
                deleted,
            )
        elif deleted:
            logger.info(
                "supersede(pending commit) tid=%s uid=%s new=%s deleted=%s",
                tenant_id,
                user_id,
                new_key,
                deleted,
            )
    finally:
        if own_session:
            session.close()
    return deleted


__all__ = [
    "same_topic",
    "find_superseded_keys",
    "supersede_user_domain",
    "bigram_jaccard",
    "normalize_slug",
]
