"""写回记忆 + 缓存 + 审计（对话写入经 UnifiedMemoryService，Task 34.03）。"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

from sqlalchemy import text

from backend.core.memory_service import get_unified_memory_service
from backend.database.pgvector_session import CacheEntry, get_pg_session
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState


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

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        mock = os.getenv("LLM_MOCK", "true").lower() == "true"
        if mock and response:
            query_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
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
                "input": message,
                "output": response,
                "model": state.get("selected_model", ""),
                "in_tok": len(message),
                "out_tok": len(response or ""),
                "cost": state.get("total_cost", 0.0),
                "latency": state.get("pipeline_latency_ms", 0.0),
                "err": state.get("error_code"),
            },
        )
        session.commit()

    return state
