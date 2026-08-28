"""LLM Harness — token / cost / LangFuse + real stream"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from backend.core.cost_manager import (
    COST_TABLE,
    calculate_cost,
    check_budget,
    count_message_tokens,
    count_tokens,
    estimate_cost,
    record_consumption,
)
from backend.core.fallback import get_fallback
from backend.core.key_repository import LLMKey
from packages.harness.base import Harness, HarnessResult
from packages.harness.provider import (
    get_llm_provider,
    load_fixture,
    mock_response,
    save_fixture,
)

logger = logging.getLogger(__name__)

_MAX_MODEL_FALLBACKS = 2


async def _budget_allows(tenant_id: str, estimated: float) -> bool:
    """mock/replay 不花钱,跳过预算检查(本地 demo/测试不被拦);
    真实 provider(record/openai)保留预算拦截。"""
    if get_llm_provider() in ("mock", "replay"):
        return True
    return await check_budget(tenant_id, estimated)


async def _wallet_allows(tenant_id: str, estimated: float) -> bool:
    if get_llm_provider() in ("mock", "replay"):
        return True
    from packages.billing.context import get_billing_context
    from packages.billing.wallet import check_wallet_allows

    ctx = get_billing_context()
    return await check_wallet_allows(tenant_id, estimated, ctx.credential_kind)


async def _terms_allows(tenant_id: str) -> bool:
    if get_llm_provider() in ("mock", "replay"):
        return True
    from packages.billing.context import get_billing_context
    from packages.terms.service import is_terms_enforcement_enabled, list_pending_terms

    if not is_terms_enforcement_enabled():
        return True
    ctx = get_billing_context()
    uid = (ctx.user_id or "").strip()
    if not uid:
        return True
    pending = list_pending_terms(
        tenant_id=tenant_id,
        user_id=uid,
        credential_kind=ctx.credential_kind,
    )
    return not pending


def _completion_kwargs(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    stream: bool = False,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
    }
    if stream:
        params["stream"] = True
    if max_tokens:
        params["max_tokens"] = int(max_tokens)
    return params


def _models_to_try(base_model: str) -> list[str]:
    from backend.core.model_registry import fallback_chain

    base = (base_model or "").strip() or "default"
    alts = fallback_chain(base)[:_MAX_MODEL_FALLBACKS]
    out: list[str] = [base]
    for name in alts:
        if name not in out:
            out.append(name)
    return out


def _pipeline_key_chain(
    *,
    tenant_id: str,
    key_provider: str,
    api_key: str,
    base_url: str | None,
) -> list[LLMKey]:
    if not api_key:
        return []
    return [
        LLMKey(
            id="pipeline",
            tenant_id=tenant_id or "default",
            provider=key_provider or "default",
            base_url=base_url or "",
            api_key=api_key,
            key_version=0,
            is_active=True,
            expires_at=None,
        )
    ]


async def _keys_for_model(
    tenant_id: str,
    model: str,
    *,
    api_key: str | None,
    base_url: str | None,
    key_provider: str,
    allow_pipeline: bool,
) -> list[LLMKey]:
    from backend.core.llm_credentials import get_key_chain_for_model

    chain = await get_key_chain_for_model(tenant_id, model, limit=3)
    if chain:
        return chain
    if allow_pipeline and api_key:
        return _pipeline_key_chain(
            tenant_id=tenant_id,
            key_provider=key_provider,
            api_key=api_key,
            base_url=base_url,
        )
    return []


def _record_fallback_metadata(*, original_model: str, final_model: str) -> None:
    if original_model == final_model:
        return
    try:
        from backend.observability.decorators import langfuse_context

        langfuse_context.update_current_observation(
            metadata={
                "fallback": True,
                "original_model": original_model,
                "final_model": final_model,
            }
        )
    except Exception:
        pass


class LLMHarness(Harness):
    """LLM 调用入口"""

    def __init__(self):
        super().__init__(name="llm")
        self._last_stream_model: str = ""
        self._stream_finish_reason: str = "llm_generated"

    def stream_finish_reason(self) -> str:
        """Set during ``stream`` — consumed by SSE router for done frame (Task 72 D7)."""
        return self._stream_finish_reason or "llm_generated"

    async def generate(
        self,
        model: str,
        messages: list[dict],
        tenant_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> HarnessResult:
        estimated = estimate_cost(model, kwargs.get("max_tokens") or 1000)
        if not await _terms_allows(tenant_id):
            return HarnessResult(
                output="请先阅读并同意服务条款与隐私政策。",
                type="llm",
                name=model,
                success=False,
                error="TERMS_001",
            )
        if not await _wallet_allows(tenant_id, estimated):
            return HarnessResult(
                output="余额不足，请求被拒绝。请先充值。",
                type="llm",
                name=model,
                success=False,
                error="BILLING_003",
            )
        if not await _budget_allows(tenant_id, estimated):
            return HarnessResult(
                output="预算超限，请求被拒绝。",
                type="llm",
                name=model,
                success=False,
                error="COST_001",
            )

        input_tokens = sum(count_message_tokens(m) for m in messages)
        key_id = str(kwargs.get("key_id") or kwargs.get("llm_key_id") or "").strip() or None

        from backend.core.llm_concurrency import llm_slot

        async with llm_slot(base_url=base_url, key_id=key_id):
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
                    max_tokens=kwargs.get("max_tokens"),
                    temperature=float(kwargs.get("temperature", 0.7)),
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
        record_consumption(
            tenant_id,
            cost,
            input_tokens + output_tokens,
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        try:
            from packages.token_quota import record_token_usage

            record_token_usage(tenant_id, input_tokens + output_tokens)
        except Exception:
            pass
        try:
            from backend.observability.decorators import langfuse_context

            langfuse_context.update_current_observation(
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
        from backend.core.llm_concurrency import llm_slot

        key_id = str(kwargs.get("key_id") or kwargs.get("llm_key_id") or "").strip() or None
        async with llm_slot(base_url=base_url, key_id=key_id):
            self._stream_finish_reason = "llm_generated"
            async for chunk in self._stream_unlocked(
                model, messages, tenant_id, api_key, base_url, **kwargs
            ):
                yield chunk

    async def _stream_unlocked(
        self,
        model: str,
        messages: list[dict],
        tenant_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """真流式主体（已在并发槽内）。"""
        estimated = estimate_cost(model, kwargs.get("max_tokens") or 1000)
        if not await _terms_allows(tenant_id):
            yield "请先阅读并同意服务条款与隐私政策。"
            return
        if not await _wallet_allows(tenant_id, estimated):
            yield "余额不足，请求被拒绝。请先充值。"
            return
        if not await _budget_allows(tenant_id, estimated):
            yield "预算超限，请求被拒绝。"
            return

        provider = get_llm_provider()
        input_tokens = sum(count_message_tokens(m) for m in messages)
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
            recorded = ""
            original_model = model
            final_model = model
            try:
                async for delta in self._stream_with_resilience(
                    model=model,
                    messages=messages,
                    tenant_id=tenant_id,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=float(kwargs.get("temperature", 0.7)),
                    max_tokens=kwargs.get("max_tokens"),
                    key_provider=str(kwargs.get("provider") or "default"),
                ):
                    collected.append(delta)
                    recorded += delta
                    yield delta
                final_model = getattr(self, "_last_stream_model", model)
            except Exception:
                logger.exception("LLM stream resilience exhausted")
                self._stream_finish_reason = "fallback"
                text = get_fallback("zh")
                for ch in text:
                    collected.append(ch)
                    yield ch
                return
            if provider == "record" and recorded:
                save_fixture(final_model or model, messages, recorded)
            _record_fallback_metadata(
                original_model=original_model,
                final_model=final_model or model,
            )

        output_text = "".join(collected)
        output_tokens = count_tokens(output_text)
        cost = calculate_cost(model, input_tokens + output_tokens)
        record_consumption(
            tenant_id,
            cost,
            input_tokens + output_tokens,
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        try:
            from packages.token_quota import record_token_usage

            record_token_usage(tenant_id, input_tokens + output_tokens)
        except Exception:
            pass
        try:
            from backend.observability.decorators import langfuse_context

            langfuse_context.update_current_observation(
                model=model,
                input=str(messages),
                output=output_text,
                usage={"input": input_tokens, "output": output_tokens},
            )
        except Exception:
            pass

    async def _stream_with_resilience(
        self,
        *,
        model: str,
        messages: list[dict],
        tenant_id: str,
        api_key: str | None,
        base_url: str | None,
        temperature: float,
        max_tokens: int | None,
        key_provider: str,
    ) -> AsyncIterator[str]:
        from backend.core.key_failover import should_try_next_model, stream_with_key_failover
        from backend.core.key_repository import LLMKeyRepository

        repo = LLMKeyRepository()
        last_err: BaseException | None = None

        for idx, attempt_model in enumerate(_models_to_try(model)):
            chain = await _keys_for_model(
                tenant_id,
                attempt_model,
                api_key=api_key if idx == 0 else None,
                base_url=base_url if idx == 0 else None,
                key_provider=key_provider,
                allow_pipeline=idx == 0,
            )
            if not chain:
                continue

            current_model = attempt_model

            async def _stream_once(
                plain_key: str, url: str, *, m: str = current_model
            ) -> AsyncIterator[str]:
                from openai import AsyncOpenAI

                from backend.core.openai_http import openai_client_kwargs

                client = AsyncOpenAI(
                    api_key=plain_key,
                    base_url=url or base_url or os.getenv("LLM_BASE_URL") or None,
                    **openai_client_kwargs(),
                )
                stream = await client.chat.completions.create(
                    **_completion_kwargs(
                        model=m,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                    )
                )
                task = asyncio.current_task()
                async for chunk in stream:  # type: ignore[union-attr]
                    if task is not None and task.cancelled():
                        raise asyncio.CancelledError()
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta

            try:
                async for delta in stream_with_key_failover(
                    chain,
                    _stream_once,
                    repo=repo,
                    tenant_id=tenant_id or "default",
                    provider=key_provider,
                ):
                    self._last_stream_model = attempt_model
                    yield delta
                self._last_stream_model = attempt_model
                return
            except Exception as e:
                if should_try_next_model(e):
                    last_err = e
                    logger.warning(
                        "stream model fallback: %s → next (reason=%s)",
                        attempt_model,
                        type(e).__name__,
                    )
                    continue
                raise

        if last_err is not None:
            raise last_err
        raise RuntimeError("无可用 LLM API Key")

    async def _call_api(
        self,
        model: str,
        messages: list[dict],
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        tenant_id: str = "default",
        key_provider: str = "default",
        max_tokens: int | None = 1000,
        temperature: float = 0.7,
    ) -> str:
        """OpenAI-compatible API with model-scoped key chain + model fallback (Task 72)."""
        from openai import AsyncOpenAI

        from backend.core.key_failover import call_with_key_failover, should_try_next_model
        from backend.core.key_repository import LLMKeyRepository
        from packages.harness.provider import get_llm_provider, save_fixture

        repo = LLMKeyRepository()
        llm_mode = get_llm_provider()
        last_err: BaseException | None = None
        original = model
        final_model = model

        for idx, attempt_model in enumerate(_models_to_try(model)):
            chain = await _keys_for_model(
                tenant_id,
                attempt_model,
                api_key=api_key if idx == 0 else None,
                base_url=base_url if idx == 0 else None,
                key_provider=key_provider,
                allow_pipeline=idx == 0,
            )
            if not chain:
                continue

            current_model = attempt_model

            async def _once(plain_key: str, url: str, *, m: str = current_model) -> str:
                from backend.core.openai_http import openai_client_kwargs

                client = AsyncOpenAI(
                    api_key=plain_key,
                    base_url=url or base_url or os.getenv("LLM_BASE_URL") or None,
                    **openai_client_kwargs(),
                )
                resp = await client.chat.completions.create(
                    **_completion_kwargs(
                        model=m,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                )
                text = (resp.choices[0].message.content or "").strip()
                if llm_mode == "record" and text:
                    save_fixture(m, messages, text)
                return text

            try:
                text = await call_with_key_failover(
                    chain,
                    lambda pk, url, m=current_model: _once(pk, url, m=m),
                    repo=repo,
                    tenant_id=tenant_id or "default",
                    provider=key_provider or "default",
                )
                final_model = attempt_model
                _record_fallback_metadata(original_model=original, final_model=final_model)
                return text
            except Exception as e:
                if should_try_next_model(e):
                    last_err = e
                    logger.warning(
                        "generate model fallback: %s → next (reason=%s)",
                        attempt_model,
                        type(e).__name__,
                    )
                    continue
                raise

        if last_err is not None:
            raise last_err
        raise RuntimeError("无可用 LLM API Key")
