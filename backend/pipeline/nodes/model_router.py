"""模型路由节点 — 双路径 + 成本估算 + Skill 二级权限"""

from __future__ import annotations

import os

from backend.core.cost_manager import estimate_cost
from backend.observability.decorators import observe
from backend.pipeline.state import PipelineState
from backend.skills.registry import registry

ROUTING_RULES = {
    "greeting": {
        "model": os.getenv("MODEL_CHEAP", "deepseek-chat"),
        "max_tokens": 100,
    },
    "emotion": {
        "model": os.getenv("MODEL_CHEAP", "deepseek-chat"),
        "max_tokens": 200,
    },
    "advice": {
        "model": os.getenv("MODEL_GOOD", "deepseek-chat"),
        "max_tokens": 500,
    },
    "default": {
        "model": os.getenv("MODEL_BEST", "deepseek-chat"),
        "max_tokens": 1000,
    },
}

PROVIDER_MAP = {
    "deepseek": "deepseek",
    "gpt": "openai",
    "o1": "openai",
    "o3": "openai",
    "glm": "zhipu",
    "qwen": "qwen",
}


def _detect_provider(model: str) -> str:
    model_lower = model.lower()
    for key, provider in PROVIDER_MAP.items():
        if key in model_lower:
            return provider
    return "default"


@observe(name="pipeline.model_router")
async def model_router(state: PipelineState) -> PipelineState:
    """双路径路由: Skill 短路径 / LLM 长路径"""
    intent = state.get("intent", "default") or "default"
    confidence = float(state.get("intent_confidence", 0.0) or 0.0)

    if confidence >= 0.85:
        try:
            skill = registry.get_skill_for_intent(intent, confidence)
            if skill:
                result = await registry.execute_skill(
                    skill_id=skill.id,
                    entities=state.get("entities") or {},
                    tenant_id=state["tenant_id"],
                    user_context=state.get("user_context") or {},
                )
                state["response"] = result.output
                state["finish_reason"] = (
                    "skill_executed" if result.success else (result.error or "error")
                )
                state["total_cost"] = 0.0
                state["pipeline_latency_ms"] = result.latency_ms
                if result.error == "PENDING_APPROVAL":
                    state["approval_request_id"] = result.approval_request_id
                if result.error:
                    state["error_code"] = result.error
                return state
        except Exception as e:
            state["response"] = f"Skill 执行错误: {str(e)}"
            state["finish_reason"] = "error"
            state["error_code"] = "SKILL_001"
            return state

    rule = ROUTING_RULES.get(intent, ROUTING_RULES["default"])
    state["selected_model"] = rule["model"]
    state["estimated_cost"] = estimate_cost(rule["model"], rule["max_tokens"])
    state["finish_reason"] = "routed_to_llm"
    _ = _detect_provider  # Task 18 key injection 预留
    return state


def route_short_or_long(state: PipelineState) -> str:
    """条件边: 短路径结束 → END，否则 → llm_generate"""
    fr = state.get("finish_reason", "")
    if fr in ("skill_executed", "PENDING_APPROVAL", "AUTH_002"):
        return "end"
    return "llm_generate"
