"""Task 25 Important 2A — CACHE / agent memory / RAG init-sample 行为测"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import ErrorCode
from backend.routers import performance as perf_mod
from backend.routers.agent import router as agent_router
from backend.routers.performance import router as perf_router
from backend.services.agent_service import get_agent_service


@pytest.fixture
def perf_client(monkeypatch):
    from backend.core.auth.api_key_auth import verify_api_key
    from backend.core.auth.models import TenantContext

    app = FastAPI()
    app.include_router(perf_router)
    # 路由现要求 chat:write；清缓存另需 tenant_admin
    app.dependency_overrides[verify_api_key] = lambda: TenantContext(
        "t1", "admin1", "tenant_admin", [], False
    )
    client = TestClient(app)
    yield client, monkeypatch
    app.dependency_overrides.clear()


def test_cache_stats_redis_down_returns_503_cache_001(perf_client):
    client, monkeypatch = perf_client

    async def _boom():
        raise ConnectionError("Error 61 connecting to 127.0.0.1:6379")

    monkeypatch.setattr(perf_mod.cache_manager, "get_cache_stats", _boom)
    r = client.get("/performance/cache/stats")
    assert r.status_code == 503
    body = r.json()
    assert "detail" in body
    assert body["detail"]["code"] == ErrorCode.CACHE_UNAVAILABLE.value
    assert body["detail"]["message"] == "redis_unavailable"


def test_cache_clear_redis_down_returns_503_cache_001(perf_client):
    client, monkeypatch = perf_client

    async def _boom(_pattern=None):
        raise ConnectionRefusedError("Connection refused")

    monkeypatch.setattr(perf_mod.cache_manager, "invalidate_pattern", _boom)
    r = client.post("/performance/cache/clear")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "CACHE_001"


def test_agent_memory_awaits_summary():
    app = FastAPI()
    app.include_router(agent_router)
    # Task 29 QA: agent 端点现要求 chat:write 认证——注入认证上下文
    from backend.core.auth.api_key_auth import verify_api_key
    from backend.core.auth.models import TenantContext

    app.dependency_overrides[verify_api_key] = lambda: TenantContext(
        "t1", "user1", "user", [], False
    )

    class _Svc:
        async def get_memory_summary(self, user_id: str):
            return {
                "user_id": user_id,
                "profile": {},
                "working_memory": {"conversation_length": 0, "active_tasks": 0},
                "recent_actions": 0,
            }

    app.dependency_overrides[get_agent_service] = lambda: _Svc()
    client = TestClient(app)
    # 普通 user 仅可查本人（2B / assert_user_access）
    r = client.get("/agent/memory/user1")
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == 200
    assert data["data"]["user_id"] == "user1"
    deny = client.get("/agent/memory/alice")
    assert deny.status_code == 403
    assert deny.json()["detail"]["code"] == "AUTH_004"
    app.dependency_overrides.clear()


def test_rag_init_sample_uses_add_documents(monkeypatch):
    from backend.modules.rag.routers import rag_router as rag_mod

    app = FastAPI()
    app.include_router(rag_mod.router)
    # Task 29: RAG 端点要求 chat:write 认证——注入认证上下文(用户角色含 chat:*)
    from backend.core.auth.api_key_auth import verify_api_key
    from backend.core.auth.models import TenantContext

    app.dependency_overrides[verify_api_key] = lambda: TenantContext(
        "t1", "user1", "user", [], False
    )

    kb = MagicMock()
    kb.get_stats.return_value = {"documents": 3, "chunks": 3}
    kb.delete_collection.return_value = None

    class _Loader:
        def __init__(self, manager):
            self.kb_manager = manager
            self.called = False

        def load_sample_knowledge(self):
            # 与生产路径一致: Document + add_documents
            from backend.modules.rag.core.langchain_compat import Document

            self.called = True
            self.kb_manager.add_documents(
                [Document(page_content="sample")]
            )

    monkeypatch.setattr(rag_mod, "get_kb_manager", lambda: kb)
    monkeypatch.setattr(rag_mod, "EnterpriseKnowledgeLoader", _Loader)

    client = TestClient(app)
    r = client.post("/api/rag/init/sample", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    kb.add_documents.assert_called()
    # 确认走的是复数 API，不是已删除的 add_document
    assert not hasattr(kb, "add_document") or not getattr(
        kb.add_document, "called", False
    )
