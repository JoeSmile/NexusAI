"""Coreference table — turn-scoped resolution + session warm persist (Task 65 slice 7)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from packages.plan.models import CorefEntry, CorefTable

logger = logging.getLogger(__name__)

WARM_KEY_PREFIX = "coref_table:"
MAX_ENTRIES = 20
ENTRY_TTL_S = 86_400
_PRONOUNS = ("它", "他们", "她们", "这家", "那个", "这位")
_INVALIDATE = re.compile(r"(不是那个|不是这个|算了|换一个|别管那个|重新来)", re.IGNORECASE)


def warm_coref_key(session_id: str) -> str:
    return f"{WARM_KEY_PREFIX}{session_id or 'default'}"


def _parse_table(raw: str) -> CorefTable | None:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return CorefTable.model_validate(data)
    except Exception:
        return None


def load_session_coref(state: dict[str, Any]) -> CorefTable:
    key = warm_coref_key(str(state.get("session_id") or "default"))
    warm = dict(state.get("warm_memory") or {})
    raw = warm.get(key)
    if raw:
        table = _parse_table(str(raw))
        if table is not None:
            return _prune_table(table)
    tenant_id = str(state.get("tenant_id") or "")
    user_id = str(state.get("user_id") or "")
    if tenant_id and user_id:
        try:
            from backend.database.vector_ops import list_user_memories_by_prefix

            rows = list_user_memories_by_prefix(tenant_id, user_id, key, limit=1)
            if rows:
                table = _parse_table(str(rows[0].get("value") or ""))
                if table is not None:
                    warm[key] = rows[0]["value"]
                    state["warm_memory"] = warm
                    return _prune_table(table)
        except Exception:
            logger.debug("load session coref from db failed", exc_info=True)
    return CorefTable()


async def save_session_coref(state: dict[str, Any], table: CorefTable) -> None:
    tenant_id = str(state.get("tenant_id") or "")
    user_id = str(state.get("user_id") or "")
    session_id = str(state.get("session_id") or "default")
    key = warm_coref_key(session_id)
    pruned = _prune_table(table)
    value = json.dumps(pruned.model_dump(mode="json"), ensure_ascii=False)

    from backend.core.memory_service import get_unified_memory_service

    mem = get_unified_memory_service(tenant_id=tenant_id)
    await mem.write(
        "warm",
        user_id=user_id,
        key=key,
        value=value,
        confidence=1.0,
        source="coref",
        embed=False,
    )
    warm = dict(state.get("warm_memory") or {})
    warm[key] = value
    state["warm_memory"] = warm


async def clear_session_coref(state: dict[str, Any]) -> None:
    tenant_id = str(state.get("tenant_id") or "")
    user_id = str(state.get("user_id") or "")
    session_id = str(state.get("session_id") or "default")
    key = warm_coref_key(session_id)
    try:
        from backend.database.vector_ops import delete_user_memory

        delete_user_memory(tenant_id, user_id, key)
    except Exception:
        logger.debug("clear session coref failed", exc_info=True)
    warm = dict(state.get("warm_memory") or {})
    warm.pop(key, None)
    state["warm_memory"] = warm


def should_invalidate_coref(message: str) -> bool:
    return bool(_INVALIDATE.search(message or ""))


async def invalidate_coref_if_drift(state: dict[str, Any]) -> bool:
    msg = str(state.get("message") or state.get("raw_input") or "")
    if not should_invalidate_coref(msg):
        return False
    await clear_session_coref(state)
    return True


def parse_coref_table(raw: Any) -> CorefTable | None:
    if raw is None:
        return None
    if isinstance(raw, CorefTable):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return CorefTable.model_validate(raw)
    except Exception:
        return None


def infer_coref_table(
    message: str,
    entities: dict[str, str],
    *,
    source_turn: int = 0,
) -> CorefTable:
    """Rule fallback when LLM omits coref_table."""
    text = (message or "").strip()
    if not text or not entities:
        return CorefTable()
    if not any(p in text for p in _PRONOUNS):
        return CorefTable()
    entries: list[CorefEntry] = []
    for idx, value in enumerate(entities.values()):
        canonical = str(value or "").strip()
        if not canonical:
            continue
        entries.append(
            CorefEntry(
                entity_id=f"e{idx + 1}",
                canonical=canonical,
                mentions=["它", "这家", "那个"],
                resolved_value=canonical,
                confidence=0.75,
                source_turn=source_turn,
            )
        )
        break
    return CorefTable(entries=entries[:MAX_ENTRIES])


def merge_coref_tables(session: CorefTable, fresh: CorefTable | None) -> CorefTable:
    if fresh is None or not fresh.entries:
        return _prune_table(session)
    by_id = {e.entity_id: e for e in session.entries}
    for entry in fresh.entries:
        by_id[entry.entity_id] = entry
    merged = CorefTable(entries=list(by_id.values())[:MAX_ENTRIES])
    return _prune_table(merged)


def apply_coref_to_text(text: str, table: CorefTable | None) -> str:
    if not text or table is None or not table.entries:
        return text
    out = text
    mentions: list[tuple[str, str]] = []
    for entry in table.entries:
        target = (entry.resolved_value or entry.canonical).strip()
        if not target:
            continue
        for mention in entry.mentions:
            if mention and mention in out:
                mentions.append((mention, target))
    for mention, target in sorted(mentions, key=lambda x: -len(x[0])):
        out = out.replace(mention, target)
    return out[:2000]


def apply_coref_to_plan(plan: dict[str, Any], table: CorefTable | None) -> dict[str, Any]:
    if table is None or not table.entries:
        return plan
    out = dict(plan)
    qr = dict(out.get("query_rewrite") or {})
    if qr:
        rq = str(qr.get("rewritten_query") or "")
        if rq:
            qr["rewritten_query"] = apply_coref_to_text(rq, table)
        subs = qr.get("sub_queries") or []
        if isinstance(subs, list):
            qr["sub_queries"] = [apply_coref_to_text(str(s), table) for s in subs]
        qr["coref_table"] = table.model_dump(mode="json")
        out["query_rewrite"] = qr
    goal = str(out.get("goal") or "")
    if goal:
        out["goal"] = apply_coref_to_text(goal, table)
    steps_out: list[dict[str, Any]] = []
    for step in out.get("steps") or []:
        if not isinstance(step, dict):
            continue
        s = dict(step)
        sq = s.get("sub_query")
        if sq:
            s["sub_query"] = apply_coref_to_text(str(sq), table)
        params = dict(s.get("params") or {})
        for pk in ("message", "query", "input"):
            if pk in params and params[pk]:
                params[pk] = apply_coref_to_text(str(params[pk]), table)
        s["params"] = params
        steps_out.append(s)
    out["steps"] = steps_out
    return out


def _prune_table(table: CorefTable) -> CorefTable:
    return CorefTable(entries=list(table.entries)[:MAX_ENTRIES])


def coref_table_dict(table: CorefTable | None) -> dict[str, Any] | None:
    if table is None or not table.entries:
        return None
    return table.model_dump(mode="json")
