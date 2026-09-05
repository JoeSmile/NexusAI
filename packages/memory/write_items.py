"""Task 42 — write_memory 侧结构化落库 / pending / audit 辅助。"""

from __future__ import annotations

import json
import logging
from typing import Any

from packages.audit import write_audit_sync
from packages.database.vector_ops import delete_user_memory, list_user_memories_by_prefix
from packages.memory.flywheel import record_correction_phrase, record_item_outcome
from packages.memory.item_rules import (
    extract_structured_items,
    pending_key,
    pending_value,
    pick_latest_pending,
    pronoun_hits,
    should_bind_pending,
    validate_and_reason,
)
from packages.memory.memory_service import UnifiedMemoryService
from packages.memory.types import EntityItem

logger = logging.getLogger(__name__)


def _invalidate_warm_cache(mem: UnifiedMemoryService, user_id: str) -> None:
    try:
        mem.invalidate_warm(user_id)
    except Exception:
        logger.debug("warm cache invalidate skipped", exc_info=True)


async def persist_warm_by_key(
    mem: UnifiedMemoryService,
    *,
    tenant_id: str,
    user_id: str,
    key: str,
    value: str,
    confidence: float,
    source: str,
    request_trace_id: str = "",
    embed: bool = True,
) -> str:
    """I1：按 is_sync_key 分流。返回 queued | synced | degraded。"""
    from packages.memory.extractor import is_sync_key
    from packages.memory.memory_queue import enqueue_memory_write, queue_depth
    from packages.metrics_memory import (
        observe_queue_depth,
        record_backlog_trigger,
        record_degraded,
    )

    if is_sync_key(key):
        await mem.write(
            "warm",
            user_id=user_id,
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            embed=embed,
        )
        return "synced"

    xid = enqueue_memory_write(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "key": key,
            "value": value,
            "confidence": confidence,
            "source": source,
            "request_trace_id": request_trace_id or "",
            "embed": embed,
        }
    )
    if xid:
        try:
            observe_queue_depth(queue_depth())
        except Exception:
            pass
        return "queued"

    # Redis 挂 / 积压 → 世界域同步兜底（不丢，标 degraded）
    try:
        record_backlog_trigger()
        record_degraded(1.0)
    except Exception:
        pass
    await mem.write(
        "warm",
        user_id=user_id,
        key=key,
        value=value,
        confidence=confidence,
        source=source or "degraded",
        embed=embed,
    )
    return "degraded"


def _audit(
    *,
    tenant_id: str,
    user_id: str,
    trace_id: str,
    action: str,
    input_text: str = "",
    output_text: str = "",
    error_code: str | None = None,
) -> None:
    write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "trace_id": trace_id or "",
            "input_text": (input_text or "")[:500],
            "output_text": (output_text or "")[:500],
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": error_code,
            "ip_address": "",
            "user_agent": "",
            "created_at": __import__("datetime").datetime.utcnow(),
        }
    )


def known_entity_names(tenant_id: str, user_id: str) -> set[str]:
    rows = list_user_memories_by_prefix(tenant_id, user_id, "entity:")
    names: set[str] = set()
    for r in rows:
        key = r.get("key") or ""
        if key.startswith("entity:"):
            names.add(key.split(":", 1)[1])
        try:
            val = json.loads(r.get("value") or "{}")
            if isinstance(val, dict) and val.get("name"):
                names.add(str(val["name"]))
        except Exception:
            pass
    return names


async def persist_structured_turn(
    mem: UnifiedMemoryService,
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    message: str,
    trace_id: str,
    aggregate: bool = False,
) -> None:
    """轻抽绑定 +（可选）聚合四类条目。异常由调用方吞。"""
    user_turns = mem.count_session_messages(
        user_id=user_id, session_id=session_id, role="user"
    )
    text = message or ""
    record_correction_phrase(text)

    # 1) pending upsert for pronouns
    for ant in pronoun_hits(text):
        pk = pending_key(session_id, ant)
        existing = list_user_memories_by_prefix(tenant_id, user_id, pk)
        first_ts = None
        created_turn = user_turns
        if existing:
            try:
                old = json.loads(existing[0]["value"])
                first_ts = old.get("first_mention_ts")
                created_turn = int(old.get("user_turn_at_create") or user_turns)
            except Exception:
                pass
        await mem.write(
            "warm",
            user_id=user_id,
            key=pk,
            value=pending_value(
                antecedent=ant,
                context_snippet=text,
                user_turn_at_create=created_turn,
                first_mention_ts=first_ts,
            ),
            confidence=0.5,
            source="rule_t0",
            embed=False,
        )

    # 2) structured candidates (R7 ordered)
    known = known_entity_names(tenant_id, user_id)
    candidates = extract_structured_items(text)
    if aggregate:
        # re-extract from head/tail session for convergence
        msgs = mem.list_session_messages_head_tail(
            user_id=user_id, session_id=session_id
        )
        blob = "\n".join(
            str(m.get("content") or "") for m in msgs if m.get("role") == "user"
        )
        if blob.strip():
            candidates = extract_structured_items(blob)

    accepted_entities: set[str] = set(known)

    for cand in candidates:
        item = cand.item
        # bind attempt when entity explicit
        if isinstance(item, EntityItem):
            pend_rows = list_user_memories_by_prefix(
                tenant_id, user_id, f"pending:{session_id}:"
            )
            bindable: list[tuple[str, dict[str, Any]]] = []
            for row in pend_rows:
                try:
                    payload = json.loads(row["value"])
                except Exception:
                    continue
                if should_bind_pending(
                    session_id=session_id,
                    pending_key_str=row["key"],
                    pending_payload=payload,
                    explicit_name=item.name,
                    explicit_turn=text,
                    current_user_turns=user_turns,
                ):
                    bindable.append((row["key"], payload))
            picked = pick_latest_pending(bindable)
            if picked:
                pk, payload = picked
                _audit(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    action="memory.bind_pending",
                    input_text=payload.get("antecedent", ""),
                    output_text=f"{pk}->{item.name}|span={item.source_span}",
                )
                delete_user_memory(tenant_id, user_id, pk)
                _invalidate_warm_cache(mem, user_id)

        ok, reason = validate_and_reason(
            item, cand.source_text, known_entity_names=accepted_entities
        )
        if not ok:
            record_item_outcome(
                accepted=False, reason_code=reason, item_type=item.type
            )
            _audit(
                tenant_id=tenant_id,
                user_id=user_id,
                trace_id=trace_id,
                action="memory.reject_item",
                input_text=item.source_span,
                output_text=item.text,
                error_code=reason,
            )
            continue
        record_item_outcome(accepted=True, item_type=item.type)
        # I1：世界域 entity/decision/error 入队；todo/pending 同步
        await persist_warm_by_key(
            mem,
            tenant_id=tenant_id,
            user_id=user_id,
            key=cand.key,
            value=item.model_dump_json(),
            confidence=item.confidence,
            source="rule_t0",
            request_trace_id=trace_id,
            embed=True,
        )
        if isinstance(item, EntityItem):
            accepted_entities.add(item.name)

    if aggregate:
        # expire unbound pending for this session
        for row in list_user_memories_by_prefix(
            tenant_id, user_id, f"pending:{session_id}:"
        ):
            delete_user_memory(tenant_id, user_id, row["key"])
            _invalidate_warm_cache(mem, user_id)
