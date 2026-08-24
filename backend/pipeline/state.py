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
    query_hash: str
    assembled_prompt: str | None
    gate_reason: str | None
    cache_bypass: bool  # Task 39 GAP-2 / 40.86：触发型消息不查不写 exact
    # 47b I1 — FE bubble UUIDs persisted on write_memory
    user_client_message_id: str | None
    assistant_client_message_id: str | None

    # ── 记忆 ──
    hot_memory: list[dict]
    warm_memory: dict[str, str]
    cold_memory: list[dict]
    warm_meta: dict[str, dict]
    rag_retrieved_ids: list[str]  # Task 61 — sanitized recall lineage
    retrieval_mode: str  # Task 61 — A direct / B summary+id

    # ── 分析结果 ──
    intent: str | None
    intent_confidence: float
    intent_source: str | None
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
    preferred_model: str | None  # 用户在壳内显式选择；优先于 intent 路由
    estimated_cost: float
    llm_tools: list[dict]

    # ── 结果 ──
    response: str
    finish_reason: str  # skill_executed | llm_generated | cache_hit | blocked
    student_pii_redacted: bool  # G7/I-7：出口脱敏标记（可观测）
    approval_request_id: str | None

    # ── 观测 ──
    trace_id: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    error_code: str | None
    langfuse_span: Any | None

    # ── 扩展 (Task 18/27 LLM Key) ──
    llm_api_key: str | None
    llm_base_url: str | None
    llm_key_id: str | None
    llm_key_version: int | None
    llm_key_provider: str | None  # model registry provider, for key chain failover
    llm_temperature: float | None  # 壳内偏好；None = harness 默认
    llm_max_tokens: int | None  # 壳内偏好；None = 模型 registry / harness 默认

    # ── 流式（07.07e）──
    stream_mode: bool

    # ── A/B（Task 21.04）──
    ab_experiment_id: str | None
    ab_variant: str | None
    ab_variant_config: dict

    # ── Task 43 task_plan / skill ──
    task_plan: dict | None
    query_rewrite: dict | None
    step_results: dict | None
    orchestrator_replan_count: int
    orchestrator_spawn_total: int
    loop_guard_streak_key: str | None
    loop_guard_streak_count: int
    loop_guard_invoke_total: int
    blackboard: list[dict]
    render_directive: dict | None  # Task 63 — {component, payload}
    render_action: dict | None  # Task 63 — FE component callback context
    short_path_skill: dict | None  # {id, name} — Chat skills registry
    skill_asset_hit: dict | None  # skill_assets CoT template hit
    triggered_run: dict | None  # 40.86 {run_id, workflow_id, ...}

    # ── Task 65 slice 6 — clarification loop ──
    pending_clarification: bool
    clarification: dict | None
    clarification_resolved: bool

    # ── Task 62 — AgentType / slots ──
    agent_type_id: str | None
    slot_values: dict[str, Any]
    agent_instances: list[dict[str, Any]]


def make_initial_state(
    tenant_id: str,
    user_id: str,
    session_id: str,
    message: str,
    user_context: dict | None = None,
    trace_id: str | None = None,
    preferred_model: str | None = None,
    user_client_message_id: str | None = None,
    assistant_client_message_id: str | None = None,
    llm_temperature: float | None = None,
    llm_max_tokens: int | None = None,
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
        "query_hash": "",
        "assembled_prompt": None,
        "gate_reason": None,
        "cache_bypass": False,
        "user_client_message_id": (user_client_message_id or "").strip() or None,
        "assistant_client_message_id": (assistant_client_message_id or "").strip()
        or None,
        "hot_memory": [],
        "warm_memory": {},
        "cold_memory": [],
        "warm_meta": {},
        "rag_retrieved_ids": [],
        "retrieval_mode": "A",
        "intent": None,
        "intent_confidence": 0.0,
        "intent_source": None,
        "entities": {},
        "fingerprint": None,
        "cache_hit": False,
        "cache_value": None,
        "pii_redacted": False,
        "prompt_injection_detected": False,
        "guardrails_passed": True,
        "selected_model": "deepseek-v4-flash",
        "preferred_model": (preferred_model or "").strip() or None,
        "estimated_cost": 0.0,
        "llm_tools": [],
        "response": "",
        "finish_reason": "",
        "student_pii_redacted": False,
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
        "llm_key_provider": None,
        "llm_temperature": llm_temperature,
        "llm_max_tokens": llm_max_tokens,
        "stream_mode": False,
        "ab_experiment_id": None,
        "ab_variant": None,
        "ab_variant_config": {},
        "task_plan": None,
        "query_rewrite": None,
        "step_results": None,
        "orchestrator_replan_count": 0,
        "orchestrator_spawn_total": 0,
        "loop_guard_streak_key": None,
        "loop_guard_streak_count": 0,
        "loop_guard_invoke_total": 0,
        "blackboard": [],
        "render_directive": None,
        "render_action": None,
        "short_path_skill": None,
        "skill_asset_hit": None,
        "triggered_run": None,
        "pending_clarification": False,
        "clarification": None,
        "clarification_resolved": False,
        "agent_type_id": None,
        "slot_values": {},
        "agent_instances": [],
    }
