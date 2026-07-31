"""模型路由节点 — 双路径（短路径=Skill, 长路径=LLM）"""

from __future__ import annotations

import os

from backend.pipeline.state import PipelineState

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


async def model_router(state: PipelineState) -> PipelineState:
    """
    双路径路由:
      - 短路径: intent+confidence >= 0.85 → 尝试执行 Skill
      - 长路径: → LLM 生成
    """
    intent = state.get("intent", "default") or "default"
    confidence = state.get("intent_confidence", 0.0) or 0.0

    if confidence >= 0.85:
        try:
            from backend.skills.registry import registry

            skill = registry.get_skill_for_intent(intent, confidence)
            if skill:
                result = await registry.execute_skill(
                    skill_id=skill.id,
                    entities=state["entities"],
                    tenant_id=state["tenant_id"],
                    user_context=state.get("user_context", {}),
                )
                state["response"] = result.output
                state["finish_reason"] = (
                    "skill_executed" if result.success else result.error
                )
                state["total_cost"] = 0.0
                if result.error == "PENDING_APPROVAL":
                    state["approval_request_id"] = result.approval_request_id
                return state
        except ImportError:
            pass

    rule = ROUTING_RULES.get(intent, ROUTING_RULES["default"])
    state["selected_model"] = rule["model"]
    state["estimated_cost"] = 0.001
    state["finish_reason"] = "routed_to_llm"
    return state


def route_short_or_long(state: PipelineState) -> str:
    """条件边: Skill 执行完 → END，否则 → llm_generate"""
    if state.get("finish_reason") in ("skill_executed",):
        return "end"
    return "llm_generate"
