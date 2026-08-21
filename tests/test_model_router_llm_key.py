"""Task 52 P0-4 — model_router missing tenant key is a 4xx, not 500."""

from __future__ import annotations

import pytest

from backend.core.errors import ErrorCode, NexusAIException
from backend.pipeline.nodes.model_router import model_router
from backend.pipeline.state import make_initial_state


@pytest.mark.asyncio
async def test_missing_credential_sets_llm_key_001(monkeypatch) -> None:
    async def _boom(*_a, **_k):
        raise NexusAIException(ErrorCode.LLM_KEY_MISSING.value, "missing")

    monkeypatch.setattr(
        "backend.pipeline.nodes.model_router.resolve_tenant_credential", _boom
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.model_router.select_model_for_intent",
        lambda _intent: type("S", (), {"name": "deepseek-v4-flash", "provider": "deepseek", "max_tokens": 100, "base_url": ""})(),
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.model_router.get_model", lambda _n: None
    )
    state = make_initial_state("t1", "u1", "s1", "hello")
    state["intent"] = "default"
    state["intent_confidence"] = 0.1
    out = await model_router(state)
    assert out["error_code"] == "LLM_KEY_001"
    assert out["finish_reason"] == "error"
    assert "公司 Key" in (out.get("response") or "")
    assert out.get("llm_api_key") in (None, "", [])


@pytest.mark.asyncio
async def test_credential_ok_still_routes(monkeypatch) -> None:
    class _Key:
        api_key = "sk-test"
        base_url = "https://example.test/v1"
        id = "kid"
        key_version = 1

    async def _ok(*_a, **_k):
        return _Key()

    monkeypatch.setattr(
        "backend.pipeline.nodes.model_router.resolve_tenant_credential", _ok
    )
    spec = type(
        "S",
        (),
        {
            "name": "deepseek-v4-flash",
            "provider": "deepseek",
            "max_tokens": 100,
            "base_url": "",
        },
    )()
    monkeypatch.setattr(
        "backend.pipeline.nodes.model_router.select_model_for_intent",
        lambda _intent: spec,
    )
    monkeypatch.setattr(
        "backend.pipeline.nodes.model_router.get_model", lambda _n: spec
    )
    state = make_initial_state("t1", "u1", "s1", "hello")
    state["intent_confidence"] = 0.1
    out = await model_router(state)
    assert out["finish_reason"] == "routed_to_llm"
    assert out["llm_api_key"] == "sk-test"
    assert not out.get("error_code")
