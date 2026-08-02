"""Task 26: get_llm_client 统一 mock/record/replay（EVID-08）"""

from __future__ import annotations

import pytest


@pytest.fixture
def mock_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def isolated_fixtures(monkeypatch, tmp_path):
    """隔离 fixture 目录，避免污染仓库 data/mock_data/llm。"""
    monkeypatch.setattr(
        "backend.core.harness.provider.FIXTURE_DIR", tmp_path
    )
    return tmp_path


def test_get_llm_client_mock_invoke_without_api_key(mock_provider):
    from backend.core.harness import get_llm_client

    client = get_llm_client(model="test-model")
    assert client is not None
    result = client.invoke("你好，ContextGate")
    text = getattr(result, "content", None) or str(result)
    assert "mock" in text.lower() or "已收到" in text
    assert "你好" in text or "ContextGate" in text


def test_get_llm_client_mock_is_deterministic(mock_provider):
    from backend.core.harness import get_llm_client

    client = get_llm_client(model="det-model")
    a = getattr(client.invoke("同一问题"), "content", None)
    b = getattr(client.invoke("同一问题"), "content", None)
    assert a == b


@pytest.mark.asyncio
async def test_get_llm_client_acomplete_chat_for_agent(mock_provider):
    from backend.core.harness import get_llm_client

    client = get_llm_client(model="agent-model")
    text = await client.acomplete_chat(
        [{"role": "user", "content": "今天天气怎么样"}],
        system="你是助手",
    )
    assert isinstance(text, str)
    assert text
    assert "抱歉" not in text


def test_replay_hit_returns_fixture(monkeypatch, isolated_fixtures):
    from backend.core.harness import get_llm_client
    from backend.core.harness.provider import save_fixture

    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    messages = [{"role": "user", "content": "replay-q-unique"}]
    save_fixture("replay-model", messages, "FIXTURE_HIT_RESPONSE")

    client = get_llm_client(model="replay-model")
    text = client.complete_chat(messages)
    assert text == "FIXTURE_HIT_RESPONSE"


def test_replay_miss_falls_back_to_mock(monkeypatch, isolated_fixtures):
    from backend.core.harness import get_llm_client

    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = get_llm_client(model="replay-miss-model")
    text = client.complete_chat([{"role": "user", "content": "no-fixture-here"}])
    assert "mock" in text.lower() or "已收到" in text


def test_openai_without_api_key_raises(monkeypatch):
    from backend.core.harness.llm_client import complete_via_provider

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        complete_via_provider(
            "m",
            [{"role": "user", "content": "hi"}],
            api_key="",
        )


def test_record_without_api_key_raises(monkeypatch):
    from backend.core.harness.llm_client import complete_via_provider

    monkeypatch.setenv("LLM_PROVIDER", "record")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        complete_via_provider(
            "m",
            [{"role": "user", "content": "hi"}],
            api_key=None,
        )


def test_evaluation_engine_works_without_api_key(mock_provider):
    from backend.evaluation_engine import EvaluationEngine

    engine = EvaluationEngine()
    result = engine.evaluate_response(
        user_message="你好",
        bot_response="你好，我是 ContextGate",
    )
    assert "未配置API_KEY" not in str(result.get("error", ""))
    assert result.get("accuracy_score", 0) >= 1
    assert result.get("naturalness_score", 0) >= 1
    assert result.get("safety_score", 0) >= 1


def test_rag_service_llm_available_without_api_key(mock_provider, monkeypatch):
    # 避免初始化时碰向量库
    class _FakeKB:
        def load_vectorstore(self):
            return None

        def search_similar(self, q, k=3):
            return []

        def get_retriever(self, search_kwargs=None):
            raise RuntimeError("not needed")

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    from backend.modules.rag.services.rag_service import RAGService

    svc = RAGService(kb_manager=_FakeKB())
    assert svc.llm is not None
    out = svc.ask("什么是 ContextGate？", search_k=1)
    assert out.get("answer")
    assert "LLM_API_KEY" not in str(out.get("answer", ""))


@pytest.mark.asyncio
async def test_agent_legacy_call_llm_uses_factory(mock_provider, monkeypatch):
    """Runtime 降级到 legacy 时也应走 complete_chat，不再返回固定占位文案。"""
    import backend.agent.agent_core as ac
    from backend.core.harness import get_llm_client

    monkeypatch.setattr(ac, "_agent_core_instance", None)
    agent = ac.AgentCore(llm_client=get_llm_client(model="agent-legacy"))
    text = await agent._call_llm("sys-ctx", "用户说你好")
    assert text
    assert "暂时无法调用模型服务" not in text
    assert "抱歉" not in text
