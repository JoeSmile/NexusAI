"""
PipelineState — LangGraph 管线状态定义。

⚠️ 使用 TypedDict，不是 Pydantic BaseModel！
每个节点签名: (state: PipelineState) -> PipelineState
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict


class PipelineState(TypedDict):
    # ── 身份 ──
    tenant_id: str
    user_id: str
    session_id: str
    user_context: dict  # {tenant_id, user_id, permissions, role}

    # ── 输入 ──
    message: str
    raw_input: str

    # ── 记忆 ──
    hot_memory: list[dict]
    warm_memory: dict[str, str]

    # ── 分析结果 ──
    intent: str | None
    intent_confidence: float
    entities: dict[str, str]

    # ── 缓存 ──
    fingerprint: str | None
    cache_hit: bool
    cache_value: str | None

    # ── 护栏 ──
    pii_redacted: bool
    prompt_injection_detected: bool
    guardrails_passed: bool

    # ── 路由 ──
    selected_model: str
    estimated_cost: float
    llm_tools: list[dict]

    # ── 结果 ──
    response: str
    finish_reason: str  # skill_executed | llm_generated | cache_hit | blocked
    approval_request_id: str | None

    # ── 观测 ──
    trace_id: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    error_code: str | None
    langfuse_span: Any | None

    # ── 扩展 (Task 18 LLM Key) ──
    llm_api_key: str | None
    llm_base_url: str | None
    llm_key_id: str | None
    llm_key_version: int | None

    # ── 流式（07.07e）──
    stream_mode: bool

    # ── A/B（Task 21.04）──
    ab_experiment_id: str | None
    ab_variant: str | None
    ab_variant_config: dict


def make_initial_state(
    tenant_id: str,
    user_id: str,
    session_id: str,
    message: str,
    user_context: dict | None = None,
    trace_id: str | None = None,
) -> PipelineState:
    """创建初始 PipelineState"""
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "user_context": user_context
        or {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "permissions": [],
            "role": "",
        },
        "message": message,
        "raw_input": message,
        "hot_memory": [],
        "warm_memory": {},
        "intent": None,
        "intent_confidence": 0.0,
        "entities": {},
        "fingerprint": None,
        "cache_hit": False,
        "cache_value": None,
        "pii_redacted": False,
        "prompt_injection_detected": False,
        "guardrails_passed": True,
        "selected_model": "deepseek-v4-flash",
        "estimated_cost": 0.0,
        "llm_tools": [],
        "response": "",
        "finish_reason": "",
        "approval_request_id": None,
        "trace_id": trace_id or f"tr_{uuid.uuid4().hex[:12]}",
        "total_tokens": 0,
        "total_cost": 0.0,
        "pipeline_latency_ms": 0.0,
        "error_code": None,
        "langfuse_span": None,
        "llm_api_key": None,
        "llm_base_url": None,
        "llm_key_id": None,
        "llm_key_version": None,
        "stream_mode": False,
        "ab_experiment_id": None,
        "ab_variant": None,
        "ab_variant_config": {},
    }
