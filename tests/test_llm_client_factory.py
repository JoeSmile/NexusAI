"""Task 26: get_llm_client 统一 mock/record/replay（EVID-08）"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def mock_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


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
    from backend.core.harness import get_llm_client

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
    # ask 在无文档时仍应生成 mock 回答
    out = svc.ask("什么是 ContextGate？", search_k=1)
    assert out.get("answer")
    assert "LLM_API_KEY" not in str(out.get("answer", ""))
