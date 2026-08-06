"""LLM 生成节点 — 调用 Harness"""

from __future__ import annotations

import asyncio
import os

from backend.core.fallback import get_fallback
from backend.core.harness import LLMHarness
from backend.core.prompt_service import get_prompt, resolve_prompt_label, sanitize_prompt_content
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
    ab_safe = (
        sanitize_prompt_content(system_prompt)
        if system_prompt and isinstance(system_prompt, str)
        else None
    )
    if ab_safe is not None:
        content = ab_safe
        prompt_meta: dict[str, str | None] = {
            "prompt_name": "ab_variant",
            "prompt_version": str(state.get("ab_variant") or "override"),
            "prompt_label": "ab",
            "prompt_source": "ab",
        }
    else:
        # Task 41 Slice 1: LangFuse → 内置默认；同步 SDK 丢线程池，避免堵 event loop
        # resolve_prompt_label：默认 production；LANGFUSE_PROMPT_AB=1 时按用户粘性分桶
        label = resolve_prompt_label(
            user_id=state.get("user_id"),
            tenant_id=tenant_id,
            prompt_name="chat.system",
        )
        pr = await asyncio.to_thread(get_prompt, "chat.system", label)
        content = pr.content
        prompt_meta = {
            "prompt_name": pr.name,
            "prompt_version": str(pr.version) if pr.version is not None else None,
            "prompt_label": pr.label,
            "prompt_source": pr.source,
        }
    messages.append({"role": "system", "content": content})
    messages.append({"role": "user", "content": message})

    max_tokens = 1000
    try:
        from backend.core.model_registry import get_model

        spec = get_model(model)
        if spec is not None:
            max_tokens = int(spec.max_tokens)
    except Exception:
        pass

    key_provider = state.get("llm_key_provider") or "default"
    if key_provider == "default":
        try:
            from backend.core.model_registry import get_model as _get_model

            _spec = _get_model(model)
            if _spec is not None and _spec.provider:
                key_provider = _spec.provider
        except Exception:
            pass

    result = await harness.generate(
        model=model,
        messages=messages,
        tenant_id=tenant_id,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        provider=key_provider,
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
            **prompt_meta,  # 扁平:prompt_name/prompt_version/prompt_label/prompt_source
        },
    )
    return state
