"""LLM Harness — token / cost / LangFuse + real stream"""

from __future__ import annotations

import asyncio
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
            # record / openai:真实调用 + Task 27 key failover
            return await self._call_api(
                model,
                messages,
                api_key,
                base_url,
                tenant_id=tenant_id,
                key_provider=str(kwargs.get("provider") or "default"),
                max_tokens=int(kwargs.get("max_tokens", 1000)),
            )

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
            task = asyncio.current_task()
            for ch in text:
                if task is not None and task.cancelled():
                    raise asyncio.CancelledError()
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
                task = asyncio.current_task()
                async for chunk in stream:  # type: ignore[union-attr]
                    if task is not None and task.cancelled():
                        raise asyncio.CancelledError()
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
        *,
        tenant_id: str = "default",
        key_provider: str = "default",
        max_tokens: int = 1000,
    ) -> str:
        """真实调用 OpenAI-compatible API;429/401 沿候选链切 key。"""
        from openai import AsyncOpenAI

        from backend.core.harness.provider import get_llm_provider, save_fixture
        from backend.core.key_failover import call_with_key_failover
        from backend.core.key_repository import LLMKey, LLMKeyRepository

        repo = LLMKeyRepository()
        chain = await repo.get_key_chain(
            tenant_id or "default", key_provider or "default", limit=3
        )
        if not chain:
            key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
            if not key:
                raise RuntimeError("无可用 LLM API Key")
            chain = [
                LLMKey(
                    id="fallback",
                    tenant_id=tenant_id or "default",
                    provider=key_provider or "default",
                    base_url=base_url or os.getenv("LLM_BASE_URL") or "",
                    api_key=key,
                    key_version=0,
                    is_active=True,
                    expires_at=None,
                )
            ]

        llm_mode = get_llm_provider()

        async def _once(plain_key: str, url: str) -> str:
            client = AsyncOpenAI(
                api_key=plain_key,
                base_url=url or base_url or os.getenv("LLM_BASE_URL") or None,
            )
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            if llm_mode == "record" and text:
                save_fixture(model, messages, text)
            return text

        return await call_with_key_failover(
            chain,
            _once,
            repo=repo,
            tenant_id=tenant_id or "default",
            provider=key_provider or "default",
        )
