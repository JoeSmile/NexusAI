"""LLM Harness — token / cost / LangFuse + stream"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from backend.core.cost_manager import (
    COST_TABLE,
    calculate_cost,
    check_budget,
    count_tokens,
    estimate_cost,
    record_consumption,
)
from backend.core.harness.base import Harness, HarnessResult


class LLMHarness(Harness):
    """LLM 调用入口"""

    def __init__(self):
        super().__init__(name="llm")

    async def generate(
        self,
        model: str,
        messages: list[dict],
        tenant_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> HarnessResult:
        estimated = estimate_cost(model, kwargs.get("max_tokens", 1000))
        if not await check_budget(tenant_id, estimated):
            return HarnessResult(
                output="预算超限，请求被拒绝。",
                type="llm",
                name=model,
                success=False,
                error="COST_001",
            )

        input_tokens = sum(count_tokens(m.get("content", "")) for m in messages)

        async def _call():
            return await self._call_api(model, messages, api_key, base_url)

        result = await self.wrap(
            fn=_call,
            type="llm",
            name=model,
            tenant_id=tenant_id,
            input=messages,
            metadata={
                "model": model,
                "input_tokens": input_tokens,
                "max_tokens": kwargs.get("max_tokens", 1000),
                "cost_per_token": COST_TABLE.get(model, COST_TABLE["default"]),
            },
        )

        if not result.success:
            return result

        output_tokens = count_tokens(str(result.output or ""))
        cost = calculate_cost(model, input_tokens + output_tokens)
        record_consumption(tenant_id, cost, input_tokens + output_tokens, model)

        try:
            from backend.observability.decorators import langfuse_context

            langfuse_context.update_current_generation(
                model=model,
                input=str(messages),
                output=result.output,
                usage={"input": input_tokens, "output": output_tokens},
            )
        except Exception:
            pass

        result.metadata.update(
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
            }
        )
        return result

    async def stream(
        self,
        model: str,
        messages: list[dict],
        tenant_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """边生成边 yield token（07.07e）；当前基于 generate 后切分 stub。"""
        result = await self.generate(
            model=model,
            messages=messages,
            tenant_id=tenant_id,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
        text = str(result.output or "")
        for ch in text:
            yield ch

    async def _call_api(
        self,
        model: str,
        messages: list[dict],
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> str:
        # 延迟导入，避免 harness ↔ pipeline 循环依赖
        from backend.pipeline.llm_helper import generate_text

        prompt = "\n".join(m.get("content", "") for m in messages)
        return await generate_text(
            prompt,
            model=model,
            api_key=api_key or os.getenv("LLM_API_KEY", ""),
            base_url=base_url or os.getenv("LLM_BASE_URL", ""),
        )
