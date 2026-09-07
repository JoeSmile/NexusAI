"""Task 26: get_llm_client 统一 mock/openai（EVID-08）"""

from __future__ import annotations

import pytest


@pytest.fixture
def mock_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_get_llm_client_mock_invoke_without_api_key(mock_provider):
    from packages.harness import get_llm_client

    client = get_llm_client(model="test-model")
    assert client is not None
    result = client.invoke("你好，NexusAI")
    text = getattr(result, "content", None) or str(result)
    assert "mock" in text.lower() or "已收到" in text
    assert "你好" in text or "NexusAI" in text


def test_get_llm_client_mock_is_deterministic(mock_provider):
    from packages.harness import get_llm_client

    client = get_llm_client(model="det-model")
    a = getattr(client.invoke("同一问题"), "content", None)
    b = getattr(client.invoke("同一问题"), "content", None)
    assert a == b


@pytest.mark.asyncio
async def test_get_llm_client_acomplete_chat_for_agent(mock_provider):
    from packages.harness import get_llm_client

    client = get_llm_client(model="agent-model")
    text = await client.acomplete_chat(
        [{"role": "user", "content": "今天天气怎么样"}],
        system="你是助手",
    )
    assert isinstance(text, str)
    assert text
    assert "抱歉" not in text


def test_openai_without_api_key_raises(monkeypatch):
    import packages.harness.llm_client as llm_client

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "_load_key_chain_sync", lambda *a, **k: [])
    # Config 可能仍有密钥,强制走空
    monkeypatch.setattr(
        "packages.llm.harness.Config.LLM_API_KEY", "", raising=False
    )

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        llm_client.complete_via_provider(
            "m",
            [{"role": "user", "content": "hi"}],
            api_key="",
        )
