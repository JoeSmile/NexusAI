"""LLM 生成节点 — 调用大模型（带断路器）"""

from __future__ import annotations

import os

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.fallback import get_fallback
from backend.observability.decorators import langfuse_context, observe
from backend.pipeline.llm_helper import generate_text
from backend.pipeline.state import PipelineState

llm_breaker = CircuitBreaker(name="llm", failure_threshold=3, recovery_timeout=30)


@observe(name="pipeline.llm_generate", as_type="generation")
async def llm_generate(state: PipelineState) -> PipelineState:
    """调用 LLM 生成回复（带断路器）"""
    api_key = state.get("llm_api_key") or os.getenv("LLM_API_KEY", "")
    base_url = state.get("llm_base_url") or os.getenv("LLM_BASE_URL", "")
    prompt = state.get("raw_input", state["message"])

    async def _call():
        return await generate_text(
            prompt,
            model=state["selected_model"],
            api_key=api_key or "",
            base_url=base_url or "",
        )

    try:
        response = await llm_breaker.call(fn=_call)
        state["response"] = response
        state["finish_reason"] = "llm_generated"
        state["total_tokens"] = len(prompt) + len(response)
        state["total_cost"] = state["total_tokens"] * 0.000002
        langfuse_context.update_current_generation(
            model=state["selected_model"],
            input=state["message"],
            output=state["response"],
            usage={
                "input": state.get("total_tokens", 0) // 2,
                "output": state.get("total_tokens", 0) // 2,
            },
        )
    except Exception:
        state["response"] = get_fallback("zh")
        state["finish_reason"] = "fallback"
        state["error_code"] = "LLM_002"

    return state
