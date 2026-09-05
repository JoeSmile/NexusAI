"""Task 84 S1 — RAG tenant isolation + delete/reset auth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.org.scope import OrgScope
from packages.rag.core.knowledge_base import KnowledgeBaseManager


def _user() -> TenantContext:
    return TenantContext("t-user", "u1", "user", [], False)


def _admin() -> TenantContext:
    return TenantContext("t-admin", "a1", "tenant_admin", [], False)


def test_search_similar_uses_explicit_tenant_not_instance(monkeypatch) -> None:
    seen: list[str] = []

    def _search(*, query: str, tenant_id: str, n_results: int):
        seen.append(tenant_id)
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    monkeypatch.setattr(
        "packages.rag.core.knowledge_base.vector_ops.search_knowledge",
        _search,
    )
    kb = KnowledgeBaseManager()
    kb.tenant_id = "WRONG"
    kb.search_similar("q", k=1, tenant_id="t-a")
    kb.search_similar("q", k=1, tenant_id="t-b")
    assert seen == ["t-a", "t-b"]


def test_search_with_score_filters_org_scope(monkeypatch) -> None:
    def _search(*, query: str, tenant_id: str, n_results: int):
        return {
            "documents": [["mine", "theirs"]],
            "metadatas": [
                [
                    {"org_unit_id": "unit-a", "org_path": "a"},
                    {"org_unit_id": "unit-b", "org_path": "b"},
                ]
            ],
            "distances": [[0.1, 0.2]],
        }

    monkeypatch.setattr(
        "packages.rag.core.knowledge_base.vector_ops.search_knowledge",
        _search,
    )
    scope = OrgScope(
        tenant_id="t1",
        user_id="u1",
        platform_role="user",
        primary_org_unit_id="unit-a",
        org_unit_ids=frozenset({"unit-a"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )
    kb = KnowledgeBaseManager()
    hits = kb.search_with_score("q", k=5, tenant_id="t1", org_scope=scope)
    assert len(hits) == 1
    assert hits[0][0].page_content == "mine"


def test_user_cannot_reset_knowledge_base(monkeypatch) -> None:
    from packages.rag.routers import rag_router as rag_mod

    kb = MagicMock()
    monkeypatch.setattr(rag_mod, "get_kb_manager", lambda: kb)
    app = FastAPI()
    app.include_router(rag_mod.router)
    app.dependency_overrides[verify_human_or_legacy_key] = _user
    client = TestClient(app)
    r = client.delete("/api/rag/reset")
    app.dependency_overrides.clear()
    assert r.status_code == 403
    kb.delete_collection.assert_not_called()


def test_tenant_admin_reset_deletes_caller_tenant_only(monkeypatch) -> None:
    from packages.rag.routers import rag_router as rag_mod

    kb = MagicMock()
    kb.delete_collection.return_value = None
    monkeypatch.setattr(rag_mod, "get_kb_manager", lambda: kb)
    monkeypatch.setattr("packages.rag.cache.bump_epoch", lambda *_a, **_k: None)

    app = FastAPI()
    app.include_router(rag_mod.router)
    app.dependency_overrides[verify_human_or_legacy_key] = _admin
    with patch.object(rag_mod, "_audit_rag_op"):
        client = TestClient(app)
        r = client.delete("/api/rag/reset")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    kwargs = kb.delete_collection.call_args.kwargs
    assert kwargs.get("tenant_id") == "t-admin"


@pytest.mark.asyncio
async def test_capability_rag_ask_passes_org_scope(monkeypatch) -> None:
    from packages.auth.models import TenantContext
    from packages.capability.invoke import _invoke_rag
    from packages.capability.models import CapabilityKind, CapabilityProvider, CapabilitySpec
    from packages.org.scope import OrgScope

    captured: dict = {}
    scope = OrgScope(
        tenant_id="t-a",
        user_id="u1",
        platform_role="user",
        primary_org_unit_id="ou1",
        org_unit_ids=frozenset({"ou1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )

    class _Sess:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _PG:
        def Session(self):
            return _Sess()

    def _ask(question, search_k=3, **kwargs):
        captured["kwargs"] = kwargs
        return {"answer": "ok", "knowledge_count": 0, "cache_hit": False, "cost": 0}

    monkeypatch.setattr(
        "packages.database.pgvector_session.get_pg_session",
        lambda: _PG(),
    )
    monkeypatch.setattr(
        "packages.org.scope.resolve_org_scope",
        lambda *_a, **_k: scope,
    )
    monkeypatch.setattr(
        "packages.rag.routers.rag_router.get_rag_service",
        lambda: type("S", (), {"ask": staticmethod(_ask)})(),
    )

    spec = CapabilitySpec(
        id="rag.ask",
        name="rag",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={"search_k": 3},
    )
    tenant = TenantContext("t-a", "u1", "user", ["chat:write"], False)
    frames = []
    async for f in _invoke_rag(spec, {"message": "制度怎么查"}, tenant):
        frames.append(f)
    assert captured["kwargs"].get("tenant_id") == "t-a"
    assert captured["kwargs"].get("org_scope") is scope
    assert any(f.get("event") == "done" for f in frames)
