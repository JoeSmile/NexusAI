"""Harness 模块测试"""

import pytest

from backend.core.harness import Harness


@pytest.mark.asyncio
async def test_harness_success():
    h = Harness("test")

    async def ok():
        return "hello"

    result = await h.wrap(
        fn=ok, type="test", name="test_fn", tenant_id="t1", input=None
    )
    assert result.success
    assert result.output == "hello"
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_harness_complete_reports_usage_to_langfuse(monkeypatch):
    """GAP-08 回归: usage 走 update_current_observation(update_current_generation 不存在于 SDK,曾静默失败)。"""
    from backend.core.harness.llm import LLMHarness
    import backend.observability.decorators as obs_decorators

    calls: dict = {}

    class FakeCtx:
        def update_current_observation(self, **kw):
            calls.update(kw)

        def update_current_trace(self, **kw):
            pass

    monkeypatch.setattr(obs_decorators, "langfuse_context", FakeCtx())
    monkeypatch.setattr("backend.core.harness.llm.get_llm_provider", lambda: "mock")

    h = LLMHarness()
    result = await h.generate(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "你好"}],
        tenant_id="t1",
        api_key="sk-x",
        base_url="http://x",
        max_tokens=100,
    )
    assert result.success
    assert calls.get("model") == "deepseek-v4-flash"
    usage = calls.get("usage") or {}
    assert usage.get("input", 0) > 0


@pytest.mark.asyncio
async def test_harness_timeout():
    h = Harness("test_timeout")

    async def slow():
        import asyncio

        await asyncio.sleep(10)
        return "too slow"

    result = await h.wrap(
        fn=slow,
        type="test",
        name="slow_fn",
        tenant_id="t1",
        input=None,
        metadata={"timeout": 0.1, "fallback": "fallback"},
    )
    assert not result.success
    assert result.error == "timeout"
    assert result.output == "fallback"
