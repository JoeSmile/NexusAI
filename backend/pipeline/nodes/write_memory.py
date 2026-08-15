"""写回记忆 + 缓存 + 审计（对话写入经 UnifiedMemoryService，Task 34.03）。"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import text

from backend.core.memory_service import get_unified_memory_service
from backend.database.pgvector_session import CacheEntry, get_pg_session
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


@observe(name="pipeline.write_memory")
async def write_memory(state: PipelineState) -> PipelineState:
    """保存对话到 pgvector，写入缓存和审计日志。"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    session_id = state["session_id"]
    message = state["message"]
    response = state["response"]
    trace_id = state["trace_id"]

    mem = get_unified_memory_service(tenant_id=tenant_id)
    await mem.write_turn(
        user_id=user_id,
        session_id=session_id,
        user_message=message or "",
        assistant_message=response or "",
        title=(message or "")[:80],
    )
    cold = await mem.maybe_cold_summarize(user_id=user_id, session_id=session_id)
    if cold:
        # 供观测；load_memory 下一轮才会读到 cold 表
        existing = list(state.get("cold_memory") or [])
        existing.append(
            {
                "id": cold.get("id"),
                "summary": cold.get("summary")
                or f"[msgs={cold.get('message_count')}]",
                "session_id": session_id,
            }
        )
        state["cold_memory"] = existing

    # Task 41/42: 规则抽取 → warm（失败静默；REJECT_* 进 audit）
    try:
        from backend.core.memory.extractor import get_extractor, min_confidence
        from backend.core.memory.write_items import (
            persist_structured_turn,
            persist_warm_by_key,
        )

        extractor = get_extractor()
        candidates = await extractor.extract(
            user_message=message or "",
            assistant_message=response or "",
        )
        threshold = min_confidence()
        for c in candidates:
            if c.confidence < threshold:
                continue
            # I1：is_sync_key 分流（identity/… 同步；entity/decision/error 入队）
            await persist_warm_by_key(
                mem,
                tenant_id=tenant_id,
                user_id=user_id,
                key=c.key,
                value=c.value,
                confidence=c.confidence,
                source=c.source,
                request_trace_id=trace_id or "",
            )
        await persist_structured_turn(
            mem,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            message=message or "",
            trace_id=trace_id or "",
            aggregate=False,
        )
        if cold:
            await persist_structured_turn(
                mem,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                message=message or "",
                trace_id=trace_id or "",
                aggregate=True,
            )
    except Exception as exc:  # 抽取是增强路径，永不因它 500
        logger.warning("memory extraction skipped: %s", exc)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        mock = os.getenv("LLM_MOCK", "true").lower() == "true"
        if mock and response and not state.get("cache_bypass"):
            query_hash = state.get("query_hash") or ""
            if not query_hash:
                logger.warning(
                    "write_memory: missing query_hash; skip exact cache write"
                )
            else:
                exact_key = f"exact:{tenant_id}:{user_id}:{query_hash}"
                session.execute(
                    text("DELETE FROM cache_entries WHERE cache_key = :k"),
                    {"k": exact_key},
                )
                session.add(
                    CacheEntry(
                        cache_key=exact_key,
                        cache_type="exact",
                        tenant_id=tenant_id,
                        value=response,
                        ttl_seconds=300,
                        expires_at=datetime.utcnow() + timedelta(seconds=300),
                    )
                )

            fingerprint = state.get("fingerprint")
            if fingerprint:
                template_key = f"template:{tenant_id}:{fingerprint}"
                session.execute(
                    text("DELETE FROM cache_entries WHERE cache_key = :k"),
                    {"k": template_key},
                )
                session.add(
                    CacheEntry(
                        cache_key=template_key,
                        cache_type="template",
                        tenant_id=tenant_id,
                        value=response,
                        ttl_seconds=3600,
                        expires_at=datetime.utcnow() + timedelta(seconds=3600),
                    )
                )
        elif mock and response and state.get("cache_bypass"):
            logger.info(
                "write_memory: cache_bypass; skip exact/template cache write"
            )

        session.execute(
            text("""
                INSERT INTO audit_logs
                    (tenant_id, user_id, action, trace_id,
                     input_text, output_text, model,
                     input_tokens, output_tokens, cost, latency_ms,
                     error_code)
                VALUES
                    (:tid, :uid, 'chat', :trace_id,
                     :input, :output, :model,
                     :in_tok, :out_tok, :cost, :latency,
                     :err)
            """),
            {
                "tid": tenant_id,
                "uid": user_id,
                "trace_id": trace_id,
                "input": (state.get("raw_input") or message or "")[:4000],
                "output": response,
                "model": state.get("selected_model", ""),
                "in_tok": len(state.get("raw_input") or message or ""),
                "out_tok": len(response or ""),
                "cost": state.get("total_cost", 0.0),
                "latency": state.get("pipeline_latency_ms", 0.0),
                "err": state.get("error_code"),
            },
        )
        session.commit()

    return state
