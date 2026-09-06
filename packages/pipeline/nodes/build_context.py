"""上下文组装节点 — 经 UnifiedMemoryService 预算组装 + 漂移检测（Task 34.05/34.06）。"""

from __future__ import annotations

import asyncio
import json
import logging

from packages.audit import write_audit_sync
from packages.guardrails.memory_drift import (
    MEMORY_BG_OMITTED_NOTICE,
    DriftFilterReport,
    filter_bundle_role_drift,
    should_audit_drift_key,
)
from packages.guardrails.rag_sanitize import RagSanitizeReport, sanitize_memory_bundle
from packages.memory.memory_service import (
    MEMORY_ISOLATION_HEADER,
    MemoryBundle,
    get_unified_memory_service,
)
from packages.observability.decorators import enrich_span, observe
from packages.pipeline.context_messages import current_user_content, resolved_query
from packages.pipeline.state import PipelineState
from packages.plan.retrieval_mode import (
    choose_retrieval_mode,
    token_budget_warning,
)
from packages.thread_pool import (
    assemble_timeout_s,
    run_in_embed_pool,
    run_in_io_pool,
)


def _sanitize_and_assemble_sync(
    state: PipelineState, bundle: MemoryBundle
) -> tuple[MemoryBundle, RagSanitizeReport, DriftFilterReport, str, str]:
    bundle, sanitize_report = sanitize_memory_bundle(bundle)
    bundle, drift_report = filter_bundle_role_drift(bundle)
    retrieval_mode = choose_retrieval_mode(
        candidate_count=len(bundle.cold) + len(bundle.warm),
        cold_items=bundle.cold,
        query=resolved_query(state),
    )
    mem = get_unified_memory_service(tenant_id=state["tenant_id"])
    memory_block = mem.assemble_prompt_block(
        bundle,
        query=resolved_query(state),
        user_id=str(state.get("user_id") or ""),
        retrieval_mode=retrieval_mode,
        include_hot=False,
    )
    if drift_report.dropped_warm_keys:
        block = (memory_block or "").strip()
        if block:
            memory_block = f"{block}\n\n{MEMORY_BG_OMITTED_NOTICE}"
        else:
            memory_block = f"{MEMORY_ISOLATION_HEADER}\n\n{MEMORY_BG_OMITTED_NOTICE}"
    return bundle, sanitize_report, drift_report, retrieval_mode, memory_block or ""


@observe(name="pipeline.build_context")
async def build_context(state: PipelineState) -> PipelineState:
    """组装记忆段（warm/cold → 本轮 user）；message history 由 llm_generate 多轮展开。"""
    bundle = MemoryBundle(
        hot=list(state.get("hot_memory") or []),
        warm=dict(state.get("warm_memory") or {}),
        cold=list(state.get("cold_memory") or []),
        warm_meta=dict(state.get("warm_meta") or {}),
    )
    no_att = (
        state.get("session_attachment_present") is False
        and not state.get("attachment_ids")
    )
    if not bundle.warm and not bundle.cold and no_att:
        state["memory_prompt_block"] = ""
        state["rag_retrieved_ids"] = []
        state["retrieval_mode"] = "A"
        return state
    drift_report = DriftFilterReport()
    try:
        (
            bundle,
            sanitize_report,
            drift_report,
            retrieval_mode,
            memory_block,
        ) = await asyncio.wait_for(
            run_in_embed_pool(_sanitize_and_assemble_sync, state, bundle),
            timeout=assemble_timeout_s(),
        )
    except TimeoutError:
        logging.getLogger(__name__).warning(
            "build_context assemble timed out after %.1fs", assemble_timeout_s()
        )
        sanitize_report = RagSanitizeReport()
        retrieval_mode = "A"
        memory_block = ""
    state["rag_retrieved_ids"] = list(sanitize_report.retrieved_ids)
    state["retrieval_mode"] = retrieval_mode
    state["memory_prompt_block"] = memory_block or ""
    user_content = current_user_content(state)
    warn = token_budget_warning(user_content, budget=8000)
    if warn:
        state["context_budget_warning"] = warn  # type: ignore[typeddict-item]
    audit_keys = [
        k
        for k in drift_report.dropped_warm_keys
        if should_audit_drift_key(state["tenant_id"], str(state.get("user_id") or ""), k)
    ]
    if sanitize_report.retrieved_ids or sanitize_report.flags:
        await run_in_io_pool(
            write_audit_sync,
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
            },
        )
    if audit_keys:
        await run_in_io_pool(
            write_audit_sync,
            {
                "tenant_id": state["tenant_id"],
                "user_id": state["user_id"],
                "action": "memory.role_drift",
                "trace_id": str(state.get("trace_id") or ""),
                "input_text": str(state.get("message") or "")[:200],
                "output_text": json.dumps(
                    {"dropped_keys": audit_keys},
                    ensure_ascii=False,
                )[:4000],
                "model": "memory",
            },
        )
    enrich_span(
        input_data={"message": state.get("message")},
        output_data={
            "user_content_len": len(user_content),
            "memory_prompt_block_len": len(state.get("memory_prompt_block") or ""),
        },
        metadata={
            "intent": state.get("intent"),
            "cold_count": len(bundle.cold),
            "hot_count": len(bundle.hot),
            "memory_drift_blocked": bool(drift_report.dropped_warm_keys),
            "memory_drift_dropped_keys": drift_report.dropped_warm_keys,
            "rag_retrieved_ids": sanitize_report.retrieved_ids,
            "rag_sanitize_flags": sanitize_report.flag_summary(),
            "retrieval_mode": retrieval_mode,
        },
    )
    from packages.attachments.inject import inject_session_attachments

    await inject_session_attachments(state)
    return state
