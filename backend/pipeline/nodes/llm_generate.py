"""LLM 生成节点 — 调用 Harness"""

from __future__ import annotations

import os

from backend.core.fallback import get_fallback
from backend.core.harness import LLMHarness
from backend.observability.decorators import enrich_span, observe
from backend.pipeline.state import PipelineState

harness = LLMHarness()


@observe(name="pipeline.llm_generate", as_type="generation")
async def llm_generate(state: PipelineState) -> PipelineState:
    """通过 LLMHarness 生成回复"""
    model = state.get("selected_model", "deepseek-v4-flash")
    tenant_id = state["tenant_id"]
    api_key = state.get("llm_api_key") or os.getenv("LLM_API_KEY", "")
    base_url = state.get("llm_base_url") or os.getenv("LLM_BASE_URL", "")
    message = state.get("raw_input", state["message"])

    messages: list[dict[str, str]] = []
    ab_cfg = state.get("ab_variant_config") or {}
    system_prompt = ab_cfg.get("system_prompt")
    if system_prompt and isinstance(system_prompt, str):
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message})

    max_tokens = 1000
    try:
        from backend.core.model_registry import get_model

        spec = get_model(model)
        if spec is not None:
            max_tokens = int(spec.max_tokens)
    except Exception:
        pass

    result = await harness.generate(
        model=model,
        messages=messages,
        tenant_id=tenant_id,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
    )

    state["total_tokens"] = result.metadata.get("input_tokens", 0) + result.metadata.get(
        "output_tokens", 0
    )
    state["total_cost"] = float(result.metadata.get("cost", 0.0) or 0.0)
    state["pipeline_latency_ms"] = result.latency_ms

    if not result.success:
        state["response"] = get_fallback("zh") if result.error != "COST_001" else str(
            result.output
        )
        state["finish_reason"] = result.error or "error"
        state["error_code"] = result.error or "LLM_002"
    else:
        state["response"] = str(result.output or "")
        state["finish_reason"] = "llm_generated"

    enrich_span(
        input_data={"model": model, "messages": messages},
        output_data=state.get("response"),
        metadata={
            "path": "long",
            "total_tokens": state.get("total_tokens"),
            "total_cost": state.get("total_cost"),
            "ab_variant": state.get("ab_variant"),
        },
    )
    return state
