"""Task 67 slice 2 — admin console MCP server management."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.capability.mcp_store import reset_mcp_store_for_tests
from backend.core.errors import NexusAIException, nexusai_exception_handler
from backend.routers.admin_console import router


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    reset_mcp_store_for_tests()


@pytest.fixture
def super_admin() -> TenantContext:
    return TenantContext("t1", "sa1", "super_admin", ["admin:*"], True)


@pytest.fixture
def tenant_admin() -> TenantContext:
    return TenantContext("t1", "ta1", "tenant_admin", ["chat:write"], False)


@contextmanager
def _client(tenant: TenantContext):
    app = FastAPI()
    app.add_exception_handler(NexusAIException, nexusai_exception_handler)  # type: ignore[arg-type]
    app.include_router(router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    yield TestClient(app)


def test_mcp_crud_and_test_import(super_admin: TenantContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPABILITY_UPSTREAM_MOCK", "true")

    with _client(super_admin) as client:
        r = client.post(
            "/api/admin/console/mcp/servers",
            json={
                "id": "mock",
                "transport": "http",
                "url": "https://example.com/mcp",
                "enabled": True,
            },
        )
        assert r.status_code == 200
        assert r.json()["item"]["id"] == "mock"

        r = client.get("/api/admin/console/mcp/servers")
        assert r.status_code == 200
        assert any(i["id"] == "mock" for i in r.json()["items"])

        r = client.post("/api/admin/console/mcp/servers/mock/test")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["tool_count"] >= 1
        tool_names = [t["name"] for t in body["tools"]]

        r = client.post(
            "/api/admin/console/mcp/servers/mock/import-tools",
            json={"tool_names": [tool_names[0]], "risk_overrides": {tool_names[0]: "high"}},
        )
        assert r.status_code == 200
        imported = r.json()
        assert len(imported["registered"]) == 1
        assert imported["registered"][0]["requires_approval"] is True

        r = client.delete("/api/admin/console/mcp/servers/mock")
        assert r.status_code == 200


def test_mcp_requires_super_admin(tenant_admin: TenantContext) -> None:
    with _client(tenant_admin) as client:
        r = client.get("/api/admin/console/mcp/servers")
    assert r.status_code == 403


def test_mcp_rejects_duplicate(super_admin: TenantContext) -> None:
    with _client(super_admin) as client:
        payload = {
            "id": "dup",
            "transport": "http",
            "url": "https://example.com/mcp",
        }
        assert client.post("/api/admin/console/mcp/servers", json=payload).status_code == 200
        assert client.post("/api/admin/console/mcp/servers", json=payload).status_code == 409


def test_load_all_mcp_servers_db_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.capability.mcp_store import load_all_mcp_servers, upsert_mcp_server_record

    monkeypatch.setenv(
        "MCP_SERVERS_JSON",
        '[{"id":"mock","transport":"http","url":"https://example.com/mcp","timeout_s":99}]',
    )
    upsert_mcp_server_record(
        server_id="mock",
        transport="http",
        url="https://example.com/mcp",
        timeout_s=12,
        merge_headers=False,
    )
    servers = {s.id: s for s in load_all_mcp_servers()}
    assert servers["mock"].timeout_s == 12.0
