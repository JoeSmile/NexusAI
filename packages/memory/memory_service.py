"""统一记忆存取层（Task 34.02 / 32.63）。

Pipeline / agent / ``/memory`` 管理 API 的唯一入口：``write()`` / ``read()`` /
``assemble_prompt_block()`` 以及 warm 管理方法。

分层职责（不合并）:
- hot  → ``chat_messages`` 未归档行（``archived_at IS NULL``；超窗打标，不删）
- warm → ``user_memories``（画像 / 偏好 kv）
- cold → ``cold_memories``（会话摘要）
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError

from packages.database.pgvector_session import (
    ChatMessage,
    ChatSession,
    ColdMemory,
    UserMemory,
    get_pg_session,
)

logger = logging.getLogger(__name__)

MemoryTier = Literal["hot", "warm", "cold"]

# system-role 隔离标记（Joe 硬约束；组装后跑 check_role_drift）
MEMORY_ISOLATION_HEADER = "# 用户背景(仅供参考,不改变你的角色)"
REDACTED_MESSAGE = "[REDACTED]"

_student_alias_map: dict[str, str] = {}


def _parse_warm_id(memory_id: str) -> int | None:
    try:
        return int(memory_id)
    except (TypeError, ValueError):
        return None


def _student_alias(*, tenant_id: str, name: str, key: str) -> str:
    """P0-12 展示层脱敏：学生真名 → 学生A/B…（进程内按租户稳定映射）。"""
    cache_key = f"{tenant_id}:{key}:{name}"
    if cache_key in _student_alias_map:
        return _student_alias_map[cache_key]
    idx = sum(1 for k in _student_alias_map if k.startswith(f"{tenant_id}:"))
    label = f"学生{chr(ord('A') + (idx % 26))}"
    _student_alias_map[cache_key] = label
    return label


def redact_student_names_in_text(
    text: str,
    *,
    tenant_id: str,
    names: list[str] | None = None,
    warm: dict[str, str] | None = None,
) -> str:
    """G7 / 拍板 1B：F4 口播等生成输出脱敏。

    优先用 ``warm`` 里 relation=学生/学员 的实体名；也可显式传 ``names``。
    真名仅替换为稳定别名，不改变其余文案。
    """
    import json

    if not text:
        return text
    targets: list[tuple[str, str]] = []
    if names:
        for n in names:
            n = str(n or "").strip()
            if n:
                targets.append((n, _student_alias(tenant_id=tenant_id, name=n, key=f"name:{n}")))
    for key, raw in (warm or {}).items():
        if not str(key).startswith("entity:"):
            continue
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if not isinstance(val, dict):
            continue
        rel = str(val.get("relation") or "")
        if rel not in ("学生", "学员"):
            continue
        name = str(val.get("name") or val.get("text") or "").strip()
        if not name:
            continue
        alias = _student_alias(tenant_id=tenant_id, name=name, key=str(key))
        targets.append((name, alias))
    # 长名优先，避免部分替换
    targets.sort(key=lambda t: len(t[0]), reverse=True)
    out = text
    for name, alias in targets:
        if name and name in out:
            out = out.replace(name, alias)
    return out


_DEFAULT_HOT_LIMIT = 5
_DEFAULT_MEMORY_BUDGET_RATIO = 0.30
_DEFAULT_CONTEXT_TOKENS = 8192
_DEFAULT_COLD_MIN_MESSAGES = 10  # ≈5 轮对话
_DEFAULT_COLD_HEAD_K = 25
_DEFAULT_COLD_TAIL_K = 25
_DEFAULT_DECAY_RATE = 0.9
_DEFAULT_WARM_MIN_WEIGHT = 0.05
_DEFAULT_BUNDLE_CACHE_TTL = 30
_DEFAULT_WARM_INJECT_CAP = 30


def decay_score(
    original_score: float, days_ago: float, decay_rate: float = _DEFAULT_DECAY_RATE
) -> float:
    """记忆衰减：``score * (decay_rate ** days)``（与 enhanced 路径同构）。"""
    return float(original_score) * (float(decay_rate) ** float(days_ago))


def _bundle_cache_ttl() -> int:
    raw = (os.getenv("MEMORY_BUNDLE_CACHE_TTL") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_BUNDLE_CACHE_TTL


def _warm_inject_cap() -> int:
    raw = (os.getenv("MEMORY_WARM_INJECT_CAP") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_WARM_INJECT_CAP


def _days_ago(dt: datetime | None) -> float:
    if dt is None:
        return 0.0
    naive = dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt
    return max(0.0, (datetime.utcnow() - naive).total_seconds() / 86400.0)


def _cold_min_messages() -> int:
    try:
        return max(4, int(os.getenv("COLD_SUMMARY_MIN_MESSAGES") or _DEFAULT_COLD_MIN_MESSAGES))
    except ValueError:
        return _DEFAULT_COLD_MIN_MESSAGES


def rule_based_session_summary(messages: list[dict[str, Any]]) -> str:
    """零 LLM 规则摘要：开场 + 要点句 + 近况 + 助手末回（Task 34.05）。"""
    if not messages:
        return ""
    users = [m for m in messages if (m.get("role") or "") == "user" and m.get("content")]
    assts = [
        m for m in messages if (m.get("role") or "") == "assistant" and m.get("content")
    ]
    parts: list[str] = []
    if users:
        parts.append(f"开场: {str(users[0]['content'])[:80]}")
    keys: list[str] = []
    for m in users[1:-1] if len(users) > 2 else []:
        c = str(m["content"])
        if any(x in c for x in ("?", "？", "吗", "如何", "怎么", "为什么")) or len(c) > 40:
            keys.append(c[:60])
    if keys:
        parts.append("要点: " + " | ".join(keys[:3]))
    if users:
        parts.append(f"近况: {str(users[-1]['content'])[:80]}")
    if assts:
        parts.append(f"助手末回: {str(assts[-1]['content'])[:80]}")
    return "；".join(parts)


@dataclass
class MemoryBundle:
    """``read()`` 三档视图。"""

    hot: list[dict[str, Any]] = field(default_factory=list)
    warm: dict[str, str] = field(default_factory=dict)
    cold: list[dict[str, Any]] = field(default_factory=list)
    warm_meta: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_pipeline_state(self) -> dict[str, Any]:
        return {
            "hot_memory": list(self.hot),
            "warm_memory": dict(self.warm),
            "cold_memory": list(self.cold),
            "warm_meta": dict(self.warm_meta),
        }


class UnifiedMemoryService:
    """统一 write / read 门面。"""

    def __init__(self, tenant_id: str = "default") -> None:
        self.tenant_id = tenant_id or "default"

    def _mem_bundle_key(
        self,
        user_id: str,
        session_id: str | None,
        *,
        hot_limit: int,
        include_warm: bool,
        include_cold: bool,
        cold_limit: int,
    ) -> str:
        """``mem:bundle:{tid}:{uid}:{session}:{hot}:{warm}:{cold}:{cold_limit}``.

        视图参数必须进 key：load_memory 与 hydrate 的 hot/cold 开关不同，
        短 key 会 30s 串包（拍板 2026-08-21 A）。失效仍扫 ``uid:*``。
        """
        from packages.redis_tools import cache_key

        view = (
            f"{session_id or '-'}:{int(hot_limit)}:"
            f"{int(include_warm)}:{int(include_cold)}:{int(cold_limit)}"
        )
        return cache_key("mem", "bundle", self.tenant_id, f"{user_id}:{view}")

    def _invalidate_mem_bundle(self, user_id: str) -> None:
        from packages.redis_tools import cache_key, get_sync_redis

        client = get_sync_redis(decode_responses=True)
        if client is None:
            return
        try:
            pattern = cache_key("mem", "bundle", self.tenant_id, f"{user_id}:*")
            keys = list(client.scan_iter(match=pattern, count=50))
            if keys:
                client.delete(*keys)
        except Exception:
            logger.debug("mem bundle cache invalidate skipped", exc_info=True)

    def _cached_bundle(
        self,
        user_id: str,
        session_id: str | None,
        *,
        hot_limit: int,
        include_warm: bool,
        include_cold: bool,
        cold_limit: int,
    ) -> MemoryBundle | None:
        from packages.redis_tools import get_sync_redis

        client = get_sync_redis(decode_responses=True)
        if client is None:
            return None
        try:
            raw = client.get(
                self._mem_bundle_key(
                    user_id,
                    session_id,
                    hot_limit=hot_limit,
                    include_warm=include_warm,
                    include_cold=include_cold,
                    cold_limit=cold_limit,
                )
            )
            if not raw:
                return None
            data = json.loads(raw)
            return MemoryBundle(
                hot=list(data.get("hot") or []),
                warm=dict(data.get("warm") or {}),
                cold=list(data.get("cold") or []),
            )
        except Exception:
            logger.debug("mem bundle cache get skipped", exc_info=True)
            return None

    def _store_bundle(
        self,
        user_id: str,
        session_id: str | None,
        bundle: MemoryBundle,
        *,
        hot_limit: int,
        include_warm: bool,
        include_cold: bool,
        cold_limit: int,
    ) -> None:
        from packages.redis_tools import get_sync_redis

        client = get_sync_redis(decode_responses=True)
        if client is None:
            return
        try:
            payload = json.dumps(
                {"hot": bundle.hot, "warm": bundle.warm, "cold": bundle.cold},
                ensure_ascii=False,
            )
            client.set(
                self._mem_bundle_key(
                    user_id,
                    session_id,
                    hot_limit=hot_limit,
                    include_warm=include_warm,
                    include_cold=include_cold,
                    cold_limit=cold_limit,
                ),
                payload,
                ex=_bundle_cache_ttl(),
            )
        except Exception:
            logger.debug("mem bundle cache set skipped", exc_info=True)

    # ── write ──────────────────────────────────────────────────────────

    async def write(
        self,
        tier: MemoryTier,
        *,
        user_id: str,
        session_id: str | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        """唯一写入口。``tier`` 决定落表。"""
        if tier == "hot":
            return await self.write_turn(
                user_id=user_id,
                session_id=str(session_id or payload.get("session_id") or ""),
                user_message=str(payload.get("user_message") or payload.get("message") or ""),
                assistant_message=str(
                    payload.get("assistant_message") or payload.get("response") or ""
                ),
                title=payload.get("title"),
            )
        if tier == "warm":
            key = str(payload["key"])
            value = str(payload["value"])
            # P0-7：forget 后禁止再写（除清除标记本身）
            if key != "__forgotten__":
                try:
                    from packages.database.vector_ops import list_user_memories_by_prefix

                    markers = list_user_memories_by_prefix(
                        self.tenant_id, user_id, "__forgotten__"
                    )
                    if any(m.get("key") == "__forgotten__" for m in markers):
                        logger.info(
                            "refuse warm write after forget tid=%s uid=%s key=%s",
                            self.tenant_id,
                            user_id,
                            key,
                        )
                        return {
                            "id": None,
                            "tier": "warm",
                            "key": key,
                            "refused": "forgotten",
                        }
                except Exception:
                    # P0-7 fail-closed：查闸门失败不得继续写
                    logger.exception(
                        "forgotten marker check failed; refuse write tid=%s uid=%s",
                        self.tenant_id,
                        user_id,
                    )
                    return {
                        "id": None,
                        "tier": "warm",
                        "key": key,
                        "refused": "forgotten_check_failed",
                    }

            superseded: list[str] = []
            from datetime import datetime as _dt

            from packages.database.embeddings import embed_text
            from packages.database.pgvector_session import UserMemory, get_pg_session
            from packages.memory.structured_summary import build_structured_summary
            from packages.memory.supersede import supersede_user_domain

            embed = bool(payload.get("embed", True))
            emb = embed_text(f"{key} {value}", tenant_id=self.tenant_id) if embed else None
            confidence = float(payload.get("confidence") or 0.5)
            source = str(payload.get("source") or "unified")
            session_factory = get_pg_session()
            with session_factory.Session() as session:
                try:
                    superseded = supersede_user_domain(
                        tenant_id=self.tenant_id,
                        user_id=user_id,
                        new_key=key,
                        new_value=value,
                        session=session,
                        commit=False,
                    )
                except Exception:
                    logger.debug("supersede skipped", exc_info=True)
                    superseded = []
                existing = (
                    session.query(UserMemory)
                    .filter_by(
                        tenant_id=self.tenant_id, user_id=user_id, key=key
                    )
                    .first()
                )
                # G3：乱序仲裁 — 消息 enqueued_at 早于现有 updated_at → 跳过
                enqueued_at = payload.get("enqueued_at")
                if existing is not None and enqueued_at is not None:
                    try:
                        msg_ts = float(enqueued_at)
                    except (TypeError, ValueError):
                        msg_ts = None
                    if msg_ts is not None and existing.updated_at is not None:
                        existing_ts = existing.updated_at.timestamp()
                        if msg_ts < existing_ts:
                            logger.info(
                                "skip stale warm write tid=%s uid=%s key=%s",
                                self.tenant_id,
                                user_id,
                                key,
                            )
                            return {
                                "id": existing.id,
                                "tier": "warm",
                                "key": key,
                                "skipped": "stale_enqueued_at",
                            }
                if existing:
                    existing.value = value
                    existing.confidence = confidence
                    existing.source = source
                    if len(value) >= 80:
                        existing.summary_meta = build_structured_summary(
                            doc_id=f"warm:{key}",
                            text=value,
                            title=key,
                            source=source,
                            confidence=confidence,
                        )
                    if embed:
                        existing.embedding = emb
                    existing.updated_at = _dt.utcnow()
                    mid = existing.id
                else:
                    row = UserMemory(
                        tenant_id=self.tenant_id,
                        user_id=user_id,
                        key=key,
                        value=value,
                        confidence=confidence,
                        source=source,
                        embedding=emb,
                        summary_meta=(
                            build_structured_summary(
                                doc_id=f"warm:{key}",
                                text=value,
                                title=key,
                                source=source,
                                confidence=confidence,
                            )
                            if len(value) >= 80
                            else None
                        ),
                    )
                    session.add(row)
                    session.flush()
                    mid = row.id
                session.commit()
            if superseded:
                try:
                    from packages.services.performance_optimizer import cache_manager

                    await cache_manager.bump_epoch(self.tenant_id)
                except Exception:
                    logger.debug("cache epoch bump skipped", exc_info=True)
            self._invalidate_mem_bundle(user_id)
            return {
                "id": mid,
                "tier": "warm",
                "key": key,
                "superseded": superseded,
            }
        if tier == "cold":
            return await self.write_cold(
                user_id=user_id,
                session_id=session_id,
                summary=str(payload.get("summary") or ""),
            )
        raise ValueError(f"unknown_memory_tier:{tier}")

    async def write_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        title: str | None = None,
        user_client_message_id: str | None = None,
        assistant_client_message_id: str | None = None,
    ) -> dict[str, Any]:
        """写入一轮对话到 ``chat_messages``（+ 确保 session 行）。"""
        if not session_id:
            raise ValueError("session_id_required")
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            existing = (
                session.query(ChatSession).filter_by(session_id=session_id).first()
            )
            if not existing:
                session.add(
                    ChatSession(
                        session_id=session_id,
                        tenant_id=self.tenant_id,
                        user_id=user_id,
                        title=(title or user_message or "")[:80],
                    )
                )
                session.flush()
            wrote_user = False
            wrote_assistant = False
            if user_message:
                wrote_user = self._add_turn_message(
                    session,
                    user_id=user_id,
                    session_id=session_id,
                    role="user",
                    content=user_message,
                    client_message_id=user_client_message_id,
                )
            if assistant_message:
                wrote_assistant = self._add_turn_message(
                    session,
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=assistant_message,
                    client_message_id=assistant_client_message_id,
                )
            session.flush()
            archived_ids = self._archive_overflow_in_session(
                session, user_id=user_id, session_id=session_id
            )
            session.commit()
        self._invalidate_mem_bundle(user_id)
        attempted = bool(user_message) or bool(assistant_message)
        duplicate = attempted and not wrote_user and not wrote_assistant and bool(
            (user_client_message_id or "").strip()
            or (assistant_client_message_id or "").strip()
        )
        return {
            "tier": "hot",
            "session_id": session_id,
            "user_id": user_id,
            "wrote_user": wrote_user,
            "wrote_assistant": wrote_assistant,
            "duplicate": duplicate,
            "archived_ids": archived_ids,
        }

    def _add_turn_message(
        self,
        session,
        *,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        client_message_id: str | None,
    ) -> bool:
        cid = (client_message_id or "").strip() or None
        if cid:
            found = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.tenant_id == self.tenant_id,
                    ChatMessage.client_message_id == cid,
                    ChatMessage.role == role,
                )
                .first()
            )
            if found is not None:
                return False
        nested = session.begin_nested() if cid else None
        try:
            session.add(
                ChatMessage(
                    tenant_id=self.tenant_id,
                    session_id=session_id,
                    user_id=user_id,
                    role=role,
                    content=content,
                    client_message_id=cid,
                )
            )
            session.flush()
            if nested is not None:
                nested.commit()
            return True
        except IntegrityError as exc:
            if nested is None:
                raise
            nested.rollback()
            err = str(getattr(exc, "orig", None) or exc).lower()
            named = "uq_chat_messages_tenant_client_role" in err
            sqlite_cid = (
                "unique constraint failed" in err and "client_message_id" in err
            )
            if named or sqlite_cid:
                logger.debug("chat turn duplicate client_message_id role=%s", role)
                return False
            raise

    def _archive_overflow_in_session(
        self, session, *, user_id: str, session_id: str
    ) -> list[int]:
        from packages.memory.turn_archive import (
            archive_window_limits,
            select_turn_ids_to_archive,
        )

        max_turns, budget = archive_window_limits()
        live = (
            session.query(ChatMessage)
            .filter_by(
                tenant_id=self.tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            .filter(ChatMessage.archived_at.is_(None))
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .all()
        )
        ids = select_turn_ids_to_archive(
            [(int(r.id), str(r.content or "")) for r in live],
            max_turns=max_turns,
            budget_tokens=budget,
        )
        if not ids:
            return []
        now = datetime.utcnow()
        session.query(ChatMessage).filter(ChatMessage.id.in_(ids)).update(
            {ChatMessage.archived_at: now},
            synchronize_session=False,
        )
        return [int(i) for i in ids]

    def read_archived_turns(
        self,
        *,
        user_id: str,
        session_id: str,
        ids: Sequence[int],
    ) -> list[dict[str, str]]:
        want = [int(i) for i in ids if i]
        if not want:
            return []
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            rows = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.tenant_id == self.tenant_id,
                    ChatMessage.user_id == user_id,
                    ChatMessage.session_id == session_id,
                    ChatMessage.id.in_(want),
                )
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                .all()
            )
        return [{"role": str(r.role), "content": str(r.content or "")} for r in rows]

    def read_l1_summary(self, *, user_id: str, session_id: str) -> str:
        from packages.memory.context_summarize import l1_warm_key

        key = l1_warm_key(session_id)
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = (
                session.query(UserMemory)
                .filter_by(
                    tenant_id=self.tenant_id,
                    user_id=user_id,
                    key=key,
                )
                .first()
            )
        if row is None or not row.value:
            return ""
        return str(row.value)

    def count_session_messages(
        self, *, user_id: str, session_id: str, role: str | None = None
    ) -> int:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            q = session.query(ChatMessage).filter_by(
                tenant_id=self.tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            if role:
                q = q.filter_by(role=role)
            return q.count()

    def list_session_messages(
        self, *, user_id: str, session_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            rows = (
                session.query(ChatMessage)
                .filter_by(
                    tenant_id=self.tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                )
                .order_by(ChatMessage.created_at.asc())
                .limit(limit)
                .all()
            )
        return [{"role": r.role, "content": r.content} for r in rows]

    def list_session_messages_head_tail(
        self,
        *,
        user_id: str,
        session_id: str,
        head_k: int = _DEFAULT_COLD_HEAD_K,
        tail_k: int = _DEFAULT_COLD_TAIL_K,
    ) -> list[dict[str, Any]]:
        """首尾取样：开场 head_k + 近况 tail_k（中间省略，对齐 32.63 首尾+关键句）。"""
        head_k = max(1, int(head_k))
        tail_k = max(1, int(tail_k))
        session_factory = get_pg_session()
        with session_factory.Session() as session:

            def _base():
                return session.query(ChatMessage).filter_by(
                    tenant_id=self.tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                )

            total = _base().count()
            if total <= 0:
                return []
            if total <= head_k + tail_k:
                rows = _base().order_by(ChatMessage.created_at.asc()).limit(total).all()
                return [{"role": r.role, "content": r.content} for r in rows]

            head_rows = (
                _base().order_by(ChatMessage.created_at.asc()).limit(head_k).all()
            )
            tail_rows = list(
                reversed(
                    _base()
                    .order_by(ChatMessage.created_at.desc())
                    .limit(tail_k)
                    .all()
                )
            )
            seen: set[Any] = {getattr(r, "id", id(r)) for r in head_rows}
            merged = list(head_rows)
            for r in tail_rows:
                rid = getattr(r, "id", id(r))
                if rid in seen:
                    continue
                merged.append(r)
                seen.add(rid)
            return [{"role": r.role, "content": r.content} for r in merged]

    async def maybe_cold_summarize(
        self,
        *,
        user_id: str,
        session_id: str,
        min_messages: int | None = None,
    ) -> dict[str, Any] | None:
        """会话消息数达阈值且为阈值整数倍时，写入规则 cold 摘要。

        阈值默认 ``COLD_SUMMARY_MIN_MESSAGES``（10）。LLM 摘要留给配置项（本轮不做）。
        消息取样：头 K + 尾 K（默认各 25），避免长会话丢「近况」。
        """
        if not session_id or not user_id:
            return None
        threshold = min_messages if min_messages is not None else _cold_min_messages()
        try:
            count = self.count_session_messages(user_id=user_id, session_id=session_id)
        except Exception:
            logger.warning("count_session_messages failed", exc_info=True)
            return None
        if count < threshold or (count % threshold) != 0:
            return None
        try:
            messages = self.list_session_messages_head_tail(
                user_id=user_id, session_id=session_id
            )
            summary = rule_based_session_summary(messages)
            if not summary:
                return None
            # 标记轮次，便于审计去重辨认
            tagged = f"[msgs={count}] {summary}"
            out = await self.write_cold(
                user_id=user_id, session_id=session_id, summary=tagged
            )
            out["message_count"] = count
            out["method"] = "rule"
            logger.info(
                "cold summary written tid=%s sid=%s msgs=%s",
                self.tenant_id,
                session_id[:12],
                count,
            )
            return out
        except Exception:
            logger.warning("maybe_cold_summarize failed", exc_info=True)
            return None

    async def write_cold(
        self,
        *,
        user_id: str,
        summary: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not (summary or "").strip():
            raise ValueError("cold_summary_required")
        from packages.memory.structured_summary import build_structured_summary

        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = ColdMemory(
                tenant_id=self.tenant_id,
                user_id=user_id,
                session_id=session_id,
                summary=summary.strip(),
            )
            session.add(row)
            session.flush()
            row.summary_meta = build_structured_summary(
                doc_id=str(row.id),
                text=summary.strip(),
                title=session_id or "session",
                source="cold",
                confidence=0.75,
            )
            session.commit()
            rid = row.id
            summary_meta = row.summary_meta
        self._invalidate_mem_bundle(user_id)
        return {
            "tier": "cold",
            "id": rid,
            "user_id": user_id,
            "summary": summary.strip(),
            "session_id": session_id,
            "summary_meta": summary_meta,
        }

    # ── read ───────────────────────────────────────────────────────────

    async def read(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        hot_limit: int = _DEFAULT_HOT_LIMIT,
        include_warm: bool = True,
        include_cold: bool = True,
        cold_limit: int = 5,
    ) -> MemoryBundle:
        """读取三档视图；失败时返回空包（不阻断调用方）。"""
        hit = self._cached_bundle(
            user_id,
            session_id,
            hot_limit=hot_limit,
            include_warm=include_warm,
            include_cold=include_cold,
            cold_limit=cold_limit,
        )
        if hit is not None:
            return hit
        try:
            bundle = self._read_sync(
                user_id=user_id,
                session_id=session_id,
                hot_limit=hot_limit,
                include_warm=include_warm,
                include_cold=include_cold,
                cold_limit=cold_limit,
            )
            self._store_bundle(
                user_id,
                session_id,
                bundle,
                hot_limit=hot_limit,
                include_warm=include_warm,
                include_cold=include_cold,
                cold_limit=cold_limit,
            )
            return bundle
        except Exception:
            logger.warning(
                "UnifiedMemoryService.read failed tid=%s uid=%s",
                self.tenant_id,
                user_id,
                exc_info=True,
            )
            return MemoryBundle()

    def _read_sync(
        self,
        *,
        user_id: str,
        session_id: str | None,
        hot_limit: int,
        include_warm: bool,
        include_cold: bool,
        cold_limit: int,
    ) -> MemoryBundle:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            q = session.query(ChatMessage).filter_by(
                tenant_id=self.tenant_id, user_id=user_id
            )
            if session_id:
                q = q.filter_by(session_id=session_id)
            q = q.filter(ChatMessage.archived_at.is_(None))
            recent = (
                q.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                .limit(hot_limit)
                .all()
            )
            hot = [
                {"role": r.role, "content": r.content}
                for r in reversed(recent)
            ]

            warm: dict[str, str] = {}
            warm_meta: dict[str, dict[str, Any]] = {}
            if include_warm:
                rows = (
                    session.query(UserMemory)
                    .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                    .all()
                )
                min_w = _DEFAULT_WARM_MIN_WEIGHT
                for r in rows:
                    if not r.key:
                        continue
                    weight = decay_score(
                        float(r.confidence if r.confidence is not None else 0.5),
                        _days_ago(r.updated_at or r.created_at),
                    )
                    if weight < min_w:
                        continue
                    warm[r.key] = r.value
                    if getattr(r, "summary_meta", None):
                        warm_meta[r.key] = dict(r.summary_meta)

            cold: list[dict[str, Any]] = []
            if include_cold:
                cq = session.query(ColdMemory).filter_by(
                    tenant_id=self.tenant_id, user_id=user_id
                )
                if session_id:
                    cq = cq.filter(
                        (ColdMemory.session_id == session_id)
                        | (ColdMemory.session_id.is_(None))
                    )
                # 多取再按衰减权重排序，保留最高权重的 cold_limit 条
                crows = (
                    cq.order_by(ColdMemory.created_at.desc())
                    .limit(max(cold_limit * 3, cold_limit))
                    .all()
                )
                scored: list[dict[str, Any]] = []
                for r in crows:
                    weight = decay_score(1.0, _days_ago(r.created_at))
                    scored.append(
                        {
                            "id": r.id,
                            "summary": r.summary,
                            "summary_meta": getattr(r, "summary_meta", None),
                            "session_id": r.session_id,
                            "created_at": (
                                r.created_at.isoformat() if r.created_at else None
                            ),
                            "weight": weight,
                        }
                    )
                scored.sort(key=lambda x: float(x.get("weight") or 0), reverse=True)
                kept = scored[:cold_limit]
                kept.sort(key=lambda x: x.get("created_at") or "")
                cold = kept

        return MemoryBundle(hot=hot, warm=warm, cold=cold, warm_meta=warm_meta)

    def load_document_by_id_sync(
        self,
        *,
        user_id: str,
        doc_id: str,
    ) -> dict[str, Any] | None:
        """Sync variant for plan param resolution (Mode B lazy-load)."""
        raw = str(doc_id or "").strip()
        if not raw:
            return None
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            if raw.startswith("warm:"):
                key = raw.split(":", 1)[1]
                row = (
                    session.query(UserMemory)
                    .filter_by(tenant_id=self.tenant_id, user_id=user_id, key=key)
                    .first()
                )
                if not row:
                    return None
                return {
                    "doc_id": raw,
                    "tier": "warm",
                    "body": row.value,
                    "summary_meta": getattr(row, "summary_meta", None),
                }
            try:
                cid = int(raw)
            except ValueError:
                return None
            row = (
                session.query(ColdMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id, id=cid)
                .first()
            )
            if not row:
                return None
            return {
                "doc_id": str(row.id),
                "tier": "cold",
                "body": row.summary,
                "summary_meta": getattr(row, "summary_meta", None),
            }

    async def load_document_by_id(
        self,
        *,
        user_id: str,
        doc_id: str,
    ) -> dict[str, Any] | None:
        """Mode B lazy-load: fetch full memory body by cold id or warm key."""
        return self.load_document_by_id_sync(user_id=user_id, doc_id=doc_id)

    async def delete_warm(self, *, user_id: str, memory_id: str) -> bool:
        """删除单条 warm（user_memories）；不级联 cold/画像全集。禁删 forget 闸门。"""
        row_id = _parse_warm_id(memory_id)
        if row_id is None:
            return False
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = (
                session.query(UserMemory)
                .filter_by(
                    tenant_id=self.tenant_id, user_id=user_id, id=row_id
                )
                .first()
            )
            if not row:
                return False
            if row.key == "__forgotten__":
                logger.warning(
                    "refuse delete forget marker tid=%s uid=%s id=%s",
                    self.tenant_id,
                    user_id,
                    memory_id,
                )
                return False
            session.delete(row)
            session.commit()
        self._invalidate_mem_bundle(user_id)
        return True

    async def update_warm_value(
        self, user_id: str, memory_id: str, new_value: str
    ) -> bool:
        """Edit warm value in place (47b slice 3)."""
        text = (new_value or "").strip()
        row_id = _parse_warm_id(memory_id)
        if not text or row_id is None:
            return False
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = (
                session.query(UserMemory)
                .filter_by(
                    tenant_id=self.tenant_id, user_id=user_id, id=row_id
                )
                .first()
            )
            if not row or row.key == "__forgotten__":
                return False
            row.value = text
            session.commit()
        self._invalidate_mem_bundle(user_id)
        return True

    async def forget_user(self, user_id: str) -> dict[str, Any]:
        """被遗忘权：删除该用户全部 warm+cold（含 hub:*）；chat_messages 脱敏保留。

        PG ``__forgotten__`` 与删除同事务写入（fail-closed）；Redis tombstone/purge 尽力。
        """
        if not user_id:
            raise ValueError("user_id_required")
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            warm_n = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .filter(UserMemory.key != "__forgotten__")
                .delete(synchronize_session=False)
            )
            cold_n = (
                session.query(ColdMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .delete(synchronize_session=False)
            )
            msg_n = (
                session.query(ChatMessage)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .filter(ChatMessage.content != REDACTED_MESSAGE)
                .update(
                    {ChatMessage.content: REDACTED_MESSAGE},
                    synchronize_session=False,
                )
            )
            # 同事务落持久闸门（P0-7）
            marker = (
                session.query(UserMemory)
                .filter_by(
                    tenant_id=self.tenant_id,
                    user_id=user_id,
                    key="__forgotten__",
                )
                .first()
            )
            now = datetime.utcnow()
            if marker:
                marker.value = now.isoformat()
                marker.updated_at = now
                marker.source = "forget"
            else:
                session.add(
                    UserMemory(
                        tenant_id=self.tenant_id,
                        user_id=user_id,
                        key="__forgotten__",
                        value=now.isoformat(),
                        confidence=1.0,
                        source="forget",
                        embedding=None,
                    )
                )
            session.commit()
        self._invalidate_mem_bundle(user_id)
        logger.info(
            "forget_user tid=%s uid=%s warm=%s cold=%s redacted_msgs=%s",
            self.tenant_id,
            user_id,
            warm_n,
            cold_n,
            msg_n,
        )
        try:
            from packages.services.performance_optimizer import cache_manager

            await cache_manager.bump_epoch(self.tenant_id)
        except Exception:
            logger.debug("chat cache epoch bump skipped", exc_info=True)
        from packages.memory.memory_queue import purge_user_pending, tombstone_user

        ok = tombstone_user(self.tenant_id, user_id)
        purged = purge_user_pending(self.tenant_id, user_id)
        if not ok:
            logger.warning(
                "forget redis tombstone failed tid=%s uid=%s purged=%s (PG marker ok)",
                self.tenant_id,
                user_id,
                purged,
            )
        return {
            "user_id": user_id,
            "deleted_warm": int(warm_n or 0),
            "deleted_cold": int(cold_n or 0),
            "redacted_messages": int(msg_n or 0),
            "redis_tombstone": ok,
            "purged_stream": purged,
        }

    def assemble_prompt_block(
        self,
        bundle: MemoryBundle,
        *,
        context_window_tokens: int | None = None,
        budget_ratio: float | None = None,
        query: str | None = None,
        user_id: str | None = None,
        retrieval_mode: str | None = None,
        include_hot: bool = True,
    ) -> str:
        """按 token 预算组装记忆段（Task 42 双轨：用户域常驻 + 世界域按需）。

        返回含隔离标记的文本，供 system 段拼接（不得当 user role）。
        ``pending:*`` 永不注入。世界域选择走 ``select_world_items``（Task 41 S2a）。
        ``retrieval_mode=B`` 时 cold 仅注入结构化摘要行（Task 61）。
        """
        from packages.memory.select_world_items import select_world_items
        from packages.memory.structured_summary import (
            format_summary_line,
            parse_structured_summary,
        )
        from packages.plan.retrieval_mode import normalize_retrieval_mode

        window = context_window_tokens or int(
            os.getenv("MEMORY_CONTEXT_TOKENS") or _DEFAULT_CONTEXT_TOKENS
        )
        ratio = budget_ratio
        if ratio is None:
            try:
                ratio = float(os.getenv("MEMORY_BUDGET_RATIO") or _DEFAULT_MEMORY_BUDGET_RATIO)
            except ValueError:
                ratio = _DEFAULT_MEMORY_BUDGET_RATIO
        budget = max(64, int(window * ratio))

        def _tok(s: str) -> int:
            return max(1, len(s) // 4)

        def _parse_val(raw: str) -> dict | str:
            try:
                obj = json.loads(raw)
                return obj if isinstance(obj, dict) else raw
            except Exception:
                return raw

        load_mode = normalize_retrieval_mode(retrieval_mode)
        mem_mode = (os.getenv("MEMORY_RETRIEVAL_MODE") or "semantic").strip()
        if mem_mode not in ("keyword", "semantic"):
            mem_mode = "semantic"
        selected_world: set[str] | None = None
        if query and str(query).strip():
            selected_world = set(
                select_world_items(
                    str(query),
                    dict(bundle.warm or {}),
                    mode=mem_mode,  # type: ignore[arg-type]
                    tenant_id=self.tenant_id,
                    user_id=user_id,
                )
            )

        l1_lines: list[str] = []
        user_lines: list[str] = []
        todo_lines: list[str] = []
        decision_lines: list[str] = []
        error_lines: list[str] = []
        entity_lines: list[str] = []

        for key, raw in (bundle.warm or {}).items():
            if key.startswith("pending:") or key.startswith("bookmark:"):
                continue
            if key.startswith("l1_narrative:"):
                val = _parse_val(str(raw))
                if isinstance(val, dict):
                    text = str(val.get("summary") or "").strip()
                else:
                    text = str(val).strip()
                if text:
                    l1_lines.append(f"- {text}")
                continue
            val = _parse_val(str(raw))
            if key.startswith(
                (
                    "fact:",
                    "preference:",
                    "identity:",
                    "user:",
                    "profile:",
                    "style:",
                )
            ):
                display = val if isinstance(val, str) else (val.get("text") or raw)
                user_lines.append(f"- {key}: {display}")
                continue
            if key.startswith(("todo:", "decision:", "error:", "entity:")):
                if not isinstance(val, dict):
                    continue
                if key.startswith("todo:"):
                    if val.get("status", "open") == "done":
                        continue
                    owner = val.get("owner") or (
                        "自己" if val.get("owner_kind") == "self" else ""
                    )
                    todo_lines.append(
                        f"- {val.get('action') or val.get('text')} (owner:{owner or '自己'})"
                    )
                elif key.startswith("decision:"):
                    if selected_world is not None and key not in selected_world:
                        continue
                    decision_lines.append(
                        f"- {val.get('statement') or val.get('text')}"
                    )
                elif key.startswith("error:"):
                    if selected_world is not None and key not in selected_world:
                        continue
                    error_lines.append(f"- {val.get('code') or val.get('text')}")
                elif key.startswith("entity:"):
                    if selected_world is not None and key not in selected_world:
                        continue
                    rel = val.get("relation") or ""
                    name = val.get("name") or val.get("text")
                    # P0-12：学生类实体注入脱敏展示
                    if rel in ("学生", "学员"):
                        name = _student_alias(
                            tenant_id=self.tenant_id,
                            name=str(name or ""),
                            key=key,
                        )
                    entity_lines.append(f"- {name}({rel})" if rel else f"- {name}")
                continue
            # 其它遗留 key → 用户域
            display = val if isinstance(val, str) else str(raw)
            user_lines.append(f"- {key}: {display}")

        # 优先级：todo > decision > error > entity > 用户画像 > cold > hot
        # 收藏注入推迟到切片 4（事务内 warm 双写）；本轮只走 user_feedback
        cap = _warm_inject_cap()

        def _clip(lines: list[str], section_max: int) -> list[str]:
            nonlocal cap
            if cap <= 0 or not lines:
                return []
            n = min(len(lines), section_max, cap)
            cap -= n
            return lines[:n]

        parts: list[str] = [MEMORY_ISOLATION_HEADER]
        if l1_lines:
            parts.append("[滚动摘要]\n" + "\n".join(l1_lines[:3]))
        todo_keep = _clip(todo_lines, 10)
        if todo_keep:
            parts.append("[活跃待办]\n" + "\n".join(todo_keep))
        decision_keep = _clip(decision_lines, 8)
        if decision_keep:
            parts.append("[近期决策]\n" + "\n".join(decision_keep))
        error_keep = _clip(error_lines, 8)
        if error_keep:
            parts.append("[相关错误码]\n" + "\n".join(error_keep))
        entity_keep = _clip(entity_lines, 8)
        if entity_keep:
            parts.append("[用户提到的对象]\n" + "\n".join(entity_keep))
        user_keep = _clip(user_lines, len(user_lines) or 0)
        if user_keep:
            parts.append("[用户背景]\n" + "\n".join(user_keep))

        _mode = normalize_retrieval_mode(retrieval_mode)
        cold_blocks: list[str] = []
        for c in bundle.cold:
            if not c.get("summary"):
                continue
            if load_mode == "B":
                meta = parse_structured_summary(
                    c.get("summary_meta"),
                    doc_id=str(c.get("id") or ""),
                    fallback_title=str(c.get("session_id") or "session"),
                )
                if not meta.get("short_summary"):
                    meta = parse_structured_summary(
                        c.get("summary"),
                        doc_id=str(c.get("id") or ""),
                    )
                cold_blocks.append(f"- {format_summary_line(meta)}")
            else:
                cold_blocks.append(f"- {c.get('summary')}")
        hot_lines = [
            f"{m.get('role')}: {m.get('content')}"
            for m in bundle.hot
            if m.get("content")
        ]

        used = _tok("\n".join(parts))
        cold_kept: list[str] = []
        for block in reversed(cold_blocks):
            t = _tok(block)
            if used + t > budget:
                break
            cold_kept.insert(0, block)
            used += t
        if cold_kept:
            parts.append("[会话摘要]\n" + "\n".join(cold_kept))

        if include_hot:
            hot_kept: list[str] = []
            for line in reversed(hot_lines):
                t = _tok(line)
                if used + t > budget:
                    break
                hot_kept.insert(0, line)
                used += t
            if hot_kept:
                parts.append("[最近对话]\n" + "\n".join(hot_kept))

        return "\n\n".join(parts)

    # ── /memory 管理 API（原 services.memory_service 迁入，禁止旁路写）──

    async def list_warm(
        self,
        user_id: str,
        *,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            q = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .filter(UserMemory.key != "__forgotten__")
                .filter(~UserMemory.key.like("pending:%"))
            )
            if memory_type:
                q = q.filter(UserMemory.source == memory_type)
            rows = q.order_by(UserMemory.updated_at.desc()).limit(limit).all()
        return [
            {
                "id": str(r.id),
                "content": f"{r.key}: {r.value}",
                "key": r.key,
                "value": r.value,
                "importance": float(r.confidence or 0.5),
                "type": r.source or "other",
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    async def list_important_warm(
        self, user_id: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            rows = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .order_by(UserMemory.confidence.desc())
                .limit(limit)
                .all()
            )
        return [
            {
                "id": str(r.id),
                "content": f"{r.key}: {r.value}",
                "key": r.key,
                "value": r.value,
                "importance": float(r.confidence or 0.5),
                "type": r.source or "other",
            }
            for r in rows
        ]

    async def search_warm(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        from packages.database.vector_ops import search_user_memories

        results = search_user_memories(
            tenant_id=self.tenant_id,
            user_id=user_id,
            query=query,
            limit=limit,
        )
        if memory_type:
            results = [r for r in results if r.get("type") == memory_type]
        return results

    async def update_warm_importance(
        self, user_id: str, memory_id: str, new_importance: float
    ) -> bool:
        if not 0.0 <= new_importance <= 1.0:
            raise ValueError("new_importance must be between 0 and 1")
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = (
                session.query(UserMemory)
                .filter_by(
                    tenant_id=self.tenant_id, user_id=user_id, id=int(memory_id)
                )
                .first()
            )
            if not row:
                return False
            row.confidence = new_importance
            session.commit()
            return True

    async def warm_statistics(self, user_id: str) -> dict[str, Any]:
        from sqlalchemy import text

        session_factory = get_pg_session()
        with session_factory.Session() as session:
            total = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .count()
            )
            by_source = session.execute(
                text(
                    """
                    SELECT COALESCE(source, 'other') AS src, COUNT(*) AS n
                    FROM user_memories
                    WHERE tenant_id = :tid AND user_id = :uid
                    GROUP BY src
                    """
                ),
                {"tid": self.tenant_id, "uid": user_id},
            ).fetchall()
        return {
            "user_id": user_id,
            "total": total,
            "by_type": {r.src: r.n for r in by_source},
        }


def get_unified_memory_service(tenant_id: str = "default") -> UnifiedMemoryService:
    return UnifiedMemoryService(tenant_id=tenant_id)
