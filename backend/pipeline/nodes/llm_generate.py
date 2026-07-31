"""LLM 生成节点 — 调用大模型"""

from __future__ import annotations

import os

from backend.pipeline.llm_helper import generate_text
from backend.pipeline.state import PipelineState


async def llm_generate(state: PipelineState) -> PipelineState:
    """调用 LLM 生成回复"""
    api_key = state.get("llm_api_key") or os.getenv("LLM_API_KEY", "")
    base_url = state.get("llm_base_url") or os.getenv("LLM_BASE_URL", "")
    prompt = state.get("raw_input", state["message"])

    try:
        response = await generate_text(
            prompt,
            model=state["selected_model"],
            api_key=api_key or "",
            base_url=base_url or "",
        )
        state["response"] = response
        state["finish_reason"] = "llm_generated"
        state["total_tokens"] = len(prompt) + len(response)
        state["total_cost"] = state["total_tokens"] * 0.000002
    except Exception:
        state["response"] = "系统暂时繁忙，请稍后再试。"
        state["finish_reason"] = "error"
        state["error_code"] = "LLM_002"

    return state
