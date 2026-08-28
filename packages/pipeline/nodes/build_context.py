"""上下文组装节点 — 经 UnifiedMemoryService 预算组装 + 漂移检测（Task 34.05/34.06）。"""

from __future__ import annotations

import json

from backend.core.audit import write_audit_sync
from packages.guardrails.output_guard import check_role_drift
from packages.guardrails.rag_sanitize import sanitize_memory_bundle
from packages.memory.memory_service import (
    MEMORY_ISOLATION_HEADER,
    MemoryBundle,
    get_unified_memory_service,
)
from packages.plan.retrieval_mode import (
    choose_retrieval_mode,
    token_budget_warning,
)
from backend.observability.decorators import enrich_span, observe
from packages.pipeline.context_messages import resolved_query
from packages.pipeline.state import PipelineState


@observe(name="pipeline.build_context")
async def build_context(state: PipelineState) -> PipelineState:
    """组装记忆段（warm/cold → system）；hot 由 llm_generate 多轮展开。"""
    mem = get_unified_memory_service(tenant_id=state["tenant_id"])
    bundle = MemoryBundle(
        hot=list(state.get("hot_memory") or []),
        warm=dict(state.get("warm_memory") or {}),
        cold=list(state.get("cold_memory") or []),
        warm_meta=dict(state.get("warm_meta") or {}),
    )
    bundle, sanitize_report = sanitize_memory_bundle(bundle)
    state["rag_retrieved_ids"] = list(sanitize_report.retrieved_ids)
    candidate_count = len(bundle.cold) + len(bundle.warm)
    retrieval_mode = choose_retrieval_mode(
        candidate_count=candidate_count,
        cold_items=bundle.cold,
        query=resolved_query(state),
    )
    state["retrieval_mode"] = retrieval_mode
    memory_block = mem.assemble_prompt_block(
        bundle,
        query=resolved_query(state),
        user_id=str(state.get("user_id") or ""),
        retrieval_mode=retrieval_mode,
        include_hot=False,
    )
    drift_blocked = False
    if memory_block:
        drift = await check_role_drift(memory_block)
        if drift.action == "blocked":
            memory_block = MEMORY_ISOLATION_HEADER
            drift_blocked = True
    state["memory_prompt_block"] = memory_block or ""
    state["assembled_prompt"] = f"user: {resolved_query(state)}"
    warn = token_budget_warning(
        "\n".join(
            part
            for part in (memory_block, state["assembled_prompt"])
            if part
        ),
        budget=8000,
    )
    if warn:
        state["context_budget_warning"] = warn  # type: ignore[typeddict-item]
    if sanitize_report.retrieved_ids or sanitize_report.flags:
        write_audit_sync(
            {
                "tenant_id": state["tenant_id"],
                "user_id": state["user_id"],
                "action": "memory.rag_sanitize",
                "trace_id": str(state.get("trace_id") or ""),
                "input_text": str(state.get("message") or "")[:200],
                "output_text": json.dumps(
                    {
                        "rag_retrieved_ids": sanitize_report.retrieved_ids,
                        "flags": sanitize_report.flag_summary(),
                        "redacted_fragments": sanitize_report.redacted_fragments,
                    },
                    ensure_ascii=False,
                )[:4000],
                "model": "memory",
            }
        )
    enrich_span(
        input_data={"message": state.get("message")},
        output_data={
            "assembled_prompt_len": len(state["assembled_prompt"] or ""),
            "memory_prompt_block_len": len(state.get("memory_prompt_block") or ""),
        },
        metadata={
            "intent": state.get("intent"),
            "cold_count": len(bundle.cold),
            "hot_count": len(bundle.hot),
            "memory_drift_blocked": drift_blocked,
            "rag_retrieved_ids": sanitize_report.retrieved_ids,
            "rag_sanitize_flags": sanitize_report.flag_summary(),
            "retrieval_mode": retrieval_mode,
        },
    )
    return state
