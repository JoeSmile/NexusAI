"""47b slice 3 — /memory/me list / patch / delete + audit (no plaintext value)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.routers import memory as memory_mod
from backend.routers.memory import router as memory_router


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext("acme", "u1", "user", [], False)


def _app(tenant: TenantContext) -> FastAPI:
    app = FastAPI()
    app.include_router(memory_router)

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    return app


def test_list_my_memories(tenant: TenantContext) -> None:
    mem = MagicMock()
    mem.list_warm = AsyncMock(
        return_value=[
            {
                "id": "1",
                "key": "fact:星火",
                "value": "项目代号星火",
                "type": "extracted",
            }
        ]
    )
    app = _app(tenant)
    with patch.object(memory_mod, "get_unified_memory_service", return_value=mem):
        r = TestClient(app).get("/memory/me/memories")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1"
    assert body["tenant_id"] == "acme"
    assert body["total"] == 1
    assert body["memories"][0]["key"] == "fact:星火"
    mem.list_warm.assert_awaited_with("u1", memory_type=None, limit=200)


def test_patch_and_delete_my_memory_audits_without_value(
    tenant: TenantContext,
) -> None:
    mem = MagicMock()
    mem.update_warm_value = AsyncMock(return_value=True)
    mem.delete_warm = AsyncMock(return_value=True)
    app = _app(tenant)
    with (
        patch.object(memory_mod, "get_unified_memory_service", return_value=mem),
        patch.object(memory_mod, "log_audit") as audit,
    ):
        client = TestClient(app)
        p = client.patch("/memory/me/memories/9", json={"value": "secret-preference"})
        assert p.status_code == 200
        d = client.delete("/memory/me/memories/9")
        assert d.status_code == 200
    assert audit.call_count == 2
    for call in audit.call_args_list:
        kwargs = call.kwargs
        assert kwargs["action"] in ("memory.update", "memory.delete")
        assert "secret-preference" not in str(call)
        assert kwargs.get("output_text", "") == "" or "secret" not in str(
            kwargs.get("output_text", "")
        )


def test_patch_non_int_id_404(tenant: TenantContext) -> None:
    mem = MagicMock()
    mem.update_warm_value = AsyncMock(return_value=False)
    app = _app(tenant)
    with patch.object(memory_mod, "get_unified_memory_service", return_value=mem):
        r = TestClient(app).patch("/memory/me/memories/abc", json={"value": "x"})
    assert r.status_code == 404
    mem.update_warm_value.assert_awaited()


def test_patch_missing_404(tenant: TenantContext) -> None:
    mem = MagicMock()
    mem.update_warm_value = AsyncMock(return_value=False)
    app = _app(tenant)
    with patch.object(memory_mod, "get_unified_memory_service", return_value=mem):
        r = TestClient(app).patch("/memory/me/memories/99", json={"value": "x"})
    assert r.status_code == 404
