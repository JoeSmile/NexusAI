"""Capability router HTTP 最小覆盖（卡点 30.06–10 拍板 A）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.models import TenantContext
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)
from backend.core.capability.registry import CapabilityRegistry
from backend.core.errors import ContextGateException, contextgate_exception_handler
from backend.routers.capability import router


@pytest.fixture
def user_tenant() -> TenantContext:
    return TenantContext("t1", "u1", "user", [], False)


@pytest.fixture
def auditor_tenant() -> TenantContext:
    return TenantContext("t1", "a1", "auditor", [], True)


@pytest.fixture
def cap_reg() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="model:mock-local",
            name="mock-local",
            kind=CapabilityKind.MODEL,
            provider=CapabilityProvider.SELF_HOSTED,
            permission="chat:write",
            spec={"max_tokens": 32},
        )
    )
    reg.register(
        CapabilitySpec(
            id="admin-only",
            name="admin-only",
            kind=CapabilityKind.MODEL,
            provider=CapabilityProvider.CONTEXTGATE,
            permission="admin:*",
            spec={"max_tokens": 8},
        )
    )
    return reg


def _client(tenant: TenantContext, reg: CapabilityRegistry) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(ContextGateException, contextgate_exception_handler)  # type: ignore[arg-type]
    app.include_router(router)

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_api_key] = _auth
    return TestClient(app)


def test_list_capabilities_role_filter(
    user_tenant: TenantContext, cap_reg: CapabilityRegistry
) -> None:
    with patch(
        "backend.routers.capability.get_capability_registry",
        return_value=cap_reg,
    ):
        client = _client(user_tenant, cap_reg)
        r = client.get("/api/capabilities")
    assert r.status_code == 200
    body = r.json()
    ids = {i["id"] for i in body["items"]}
    assert "model:mock-local" in ids
    assert "admin-only" not in ids


def test_list_unauthorized_without_override() -> None:
    """未覆盖 verify 时缺 key → 401。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/api/capabilities")
    assert r.status_code == 401


def test_invoke_short_json(
    user_tenant: TenantContext,
    cap_reg: CapabilityRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    with (
        patch(
            "backend.routers.capability.get_capability_registry",
            return_value=cap_reg,
        ),
        patch(
            "backend.core.capability.invoke.get_capability_registry",
            return_value=cap_reg,
        ),
        patch("backend.core.capability.governance._redis", return_value=None),
        patch("backend.routers.capability.log_audit"),
    ):
        client = _client(user_tenant, cap_reg)
        r = client.post(
            "/api/capabilities/model:mock-local/invoke?stream=false",
            json={"message": "hello router"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["capability_id"] == "model:mock-local"
    assert body.get("cost_source") == "harness"
    assert isinstance(body.get("response"), str)


def test_invoke_forbidden_for_auditor(
    auditor_tenant: TenantContext, cap_reg: CapabilityRegistry
) -> None:
    with (
        patch(
            "backend.routers.capability.get_capability_registry",
            return_value=cap_reg,
        ),
        patch("backend.core.capability.governance._redis", return_value=None),
    ):
        client = _client(auditor_tenant, cap_reg)
        r = client.post(
            "/api/capabilities/model:mock-local/invoke?stream=false",
            json={"message": "nope"},
        )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "AUTH_002"
