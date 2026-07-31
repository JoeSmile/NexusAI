"""
PipelineState — LangGraph 管线状态定义。

⚠️ 使用 TypedDict，不是 Pydantic BaseModel！
每个节点签名: (state: PipelineState) -> PipelineState
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, TypedDict


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
    emotion: Optional[str]
    emotion_intensity: float
    intent: Optional[str]
    intent_confidence: float
    entities: dict[str, str]

    # ── 缓存 ──
    fingerprint: Optional[str]
    cache_hit: bool
    cache_value: Optional[str]

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
    approval_request_id: Optional[str]

    # ── 观测 ──
    trace_id: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    error_code: Optional[str]
    langfuse_span: Optional[Any]

    # ── 扩展 (Task 18 LLM Key) ──
    llm_api_key: Optional[str]
    llm_base_url: Optional[str]
    llm_key_id: Optional[str]
    llm_key_version: Optional[int]


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
        "emotion": None,
        "emotion_intensity": 5.0,
        "intent": None,
        "intent_confidence": 0.0,
        "entities": {},
        "fingerprint": None,
        "cache_hit": False,
        "cache_value": None,
        "pii_redacted": False,
        "prompt_injection_detected": False,
        "guardrails_passed": True,
        "selected_model": "deepseek-chat",
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
    }
