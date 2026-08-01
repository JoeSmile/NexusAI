"""LLM Harness — token / cost / LangFuse + real stream"""

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
from backend.core.harness.provider import (
    get_llm_provider,
    load_fixture,
    mock_response,
    save_fixture,
)


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
            provider = get_llm_provider()
            prompt = "\n".join(m.get("content", "") for m in messages)
            if provider == "mock":
                return mock_response(model, prompt)
            if provider == "replay":
                hit = load_fixture(model, messages)
                if hit is not None:
                    return hit
                return mock_response(model, prompt)
            # record / openai:真实调用(record 由 generate_text 落盘)
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
        """真流式：优先 OpenAI-compatible astream；否则 mock/降级切片。"""
        estimated = estimate_cost(model, kwargs.get("max_tokens", 1000))
        if not await check_budget(tenant_id, estimated):
            yield "预算超限，请求被拒绝。"
            return

        key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        provider = get_llm_provider()
        input_tokens = sum(count_tokens(m.get("content", "")) for m in messages)
        collected: list[str] = []
        prompt = "\n".join(m.get("content", "") for m in messages)

        if provider in ("mock", "replay"):
            text = (
                load_fixture(model, messages)
                if provider == "replay"
                else None
            )
            if text is None:
                text = mock_response(model, prompt)
            for ch in text:
                collected.append(ch)
                yield ch
        else:
            # record / openai:真流式(OpenAI-compatible astream,失败降级非流式)
            recorded = ""
            try:
                from openai import AsyncOpenAI

                client = AsyncOpenAI(
                    api_key=key,
                    base_url=base_url or os.getenv("LLM_BASE_URL") or None,
                )
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    stream=True,
                    max_tokens=int(kwargs.get("max_tokens", 1000)),
                )
                async for chunk in stream:  # type: ignore[union-attr]
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        collected.append(delta)
                        recorded += delta
                        yield delta
            except Exception:
                # 失败时降级为非流式 generate
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
                    collected.append(ch)
                    yield ch
                return
            if provider == "record" and recorded:
                save_fixture(model, messages, recorded)

        output_text = "".join(collected)
        output_tokens = count_tokens(output_text)
        cost = calculate_cost(model, input_tokens + output_tokens)
        record_consumption(tenant_id, cost, input_tokens + output_tokens, model)
        try:
            from backend.observability.decorators import langfuse_context

            langfuse_context.update_current_generation(
                model=model,
                input=str(messages),
                output=output_text,
                usage={"input": input_tokens, "output": output_tokens},
            )
        except Exception:
            pass

    async def _call_api(
        self,
        model: str,
        messages: list[dict],
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> str:
        from backend.pipeline.llm_helper import generate_text

        prompt = "\n".join(m.get("content", "") for m in messages)
        key = api_key or os.getenv("LLM_API_KEY") or ""
        url = base_url or os.getenv("LLM_BASE_URL") or ""
        return await generate_text(
            prompt,
            model=model,
            api_key=key,
            base_url=url,
        )
