"""Task 67 slice 0 — admin console routes and permission tiers."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from packages.capability.registry import CapabilityRegistry
from packages.errors import NexusAIException, nexusai_exception_handler
from apps.api.routers.admin_console import router


def _tool_spec(
    cap_id: str = "tool:demo:echo",
    *,
    status: CapabilityStatus = CapabilityStatus.ENABLED,
    tenant_allowlist: list[str] | None = None,
) -> CapabilitySpec:
    spec_body = {
        "governance": True,
        "executor": "builtin",
        "supply_origin": "builtin",
        "risk_level": "low",
        "tool_contract": {
            "name": cap_id,
            "version": "v1",
            "description": "Demo builtin tool for admin console tests",
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": {"type": "object"},
            "failure_semantics": {
                "retryable": True,
                "idempotent": True,
                "requires_compensation": False,
                "failure_codes": [],
            },
            "idempotency_key_args": [],
            "examples": [{"input": {}, "output": {}}],
        },
    }
    if tenant_allowlist is not None:
        spec_body["tenant_allowlist"] = tenant_allowlist
    return CapabilitySpec(
        id=cap_id,
        name=cap_id,
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        permission="chat:write",
        status=status,
        spec=spec_body,
    )


@pytest.fixture
def tool_reg() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(_tool_spec())
    reg.register(
        _tool_spec(
            "tool:tenant:only",
            tenant_allowlist=["t-allowed"],
        )
    )
    return reg


@contextmanager
def _client(tenant: TenantContext, reg: CapabilityRegistry):
    app = FastAPI()
    app.add_exception_handler(NexusAIException, nexusai_exception_handler)  # type: ignore[arg-type]
    app.include_router(router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    with patch("apps.api.routers.admin_console.get_capability_registry", return_value=reg), patch(
        "packages.capability.admin_store.get_capability_registry", return_value=reg
    ):
        yield TestClient(app)


@pytest.fixture
def super_admin() -> TenantContext:
    return TenantContext("t1", "sa1", "super_admin", ["admin:*"], True)


@pytest.fixture
def tenant_admin() -> TenantContext:
    return TenantContext("t-allowed", "ta1", "tenant_admin", ["chat:write"], False)


@pytest.fixture
def user() -> TenantContext:
    return TenantContext("t1", "u1", "user", ["chat:write"], False)


def test_super_admin_lists_tools(super_admin: TenantContext, tool_reg: CapabilityRegistry) -> None:
    with _client(super_admin, tool_reg) as client:
        r = client.get("/api/admin/console/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    assert any(i["id"] == "tool:demo:echo" for i in body["items"])


def test_tenant_admin_sees_allowlisted_subset(
    tenant_admin: TenantContext, tool_reg: CapabilityRegistry
) -> None:
    with _client(tenant_admin, tool_reg) as client:
        r = client.get("/api/admin/console/tools")
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    assert "tool:tenant:only" in ids
    assert "tool:demo:echo" in ids


def test_user_forbidden(user: TenantContext, tool_reg: CapabilityRegistry) -> None:
    with _client(user, tool_reg) as client:
        r = client.get("/api/admin/console/tools")
    assert r.status_code == 403


def test_super_admin_can_disable_tool(super_admin: TenantContext, tool_reg: CapabilityRegistry) -> None:
    with (
        patch("apps.api.routers.admin_console.write_audit_sync"),
        patch("packages.capability.admin_store._upsert_db_row"),
        _client(super_admin, tool_reg) as client,
    ):
        r = client.patch(
            "/api/admin/console/tools/tool:demo:echo/status",
            json={"status": "disabled"},
        )
    assert r.status_code == 200
    assert r.json()["item"]["status"] == "disabled"
    assert tool_reg.get("tool:demo:echo", require_enabled=False).status == CapabilityStatus.DISABLED


def test_tenant_admin_cannot_disable_tool(
    tenant_admin: TenantContext, tool_reg: CapabilityRegistry
) -> None:
    with _client(tenant_admin, tool_reg) as client:
        r = client.patch(
            "/api/admin/console/tools/tool:demo:echo/status",
            json={"status": "disabled"},
        )
    assert r.status_code == 403


def test_tenant_admin_can_update_own_allowlist(
    tenant_admin: TenantContext, tool_reg: CapabilityRegistry
) -> None:
    with _client(tenant_admin, tool_reg) as client:
        r = client.put(
            "/api/admin/console/tools/tool:demo:echo/tenant-allowlist",
            json={"tenant_ids": ["t-allowed"]},
        )
    assert r.status_code == 200
    assert "t-allowed" in r.json()["tenant_allowlist"]


def test_tenant_allowlist_hides_tool_from_other_tenant(tool_reg: CapabilityRegistry) -> None:
    from packages.capability.invoke import capability_visible_to

    spec = tool_reg.get("tool:tenant:only", require_enabled=False)
    allowed = TenantContext("t-allowed", "u1", "user", ["chat:write"], False)
    blocked = TenantContext("t-other", "u2", "user", ["chat:write"], False)
    assert capability_visible_to(spec, allowed) is True
    assert capability_visible_to(spec, blocked) is False


def test_exec_policy_requires_super_admin(
    tenant_admin: TenantContext, tool_reg: CapabilityRegistry
) -> None:
    with _client(tenant_admin, tool_reg) as client:
        r = client.put(
            "/api/admin/console/tools/tool:demo:echo/exec-policy",
            json={"timeout_s": 5},
        )
    assert r.status_code == 403


def test_get_tool_detail(super_admin: TenantContext, tool_reg: CapabilityRegistry) -> None:
    with _client(super_admin, tool_reg) as client:
        r = client.get("/api/admin/console/tools/tool:demo:echo")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "tool:demo:echo"
    assert "tool_contract" in body
    assert "exec_policy" in body


def test_domain_filter(super_admin: TenantContext, tool_reg: CapabilityRegistry) -> None:
    reg = tool_reg
    reg.register(
        _tool_spec(
            "tool:calendar:query",
            tenant_allowlist=None,
        )
    )
    with _client(super_admin, reg) as client:
        r = client.get("/api/admin/console/tools?domain=demo")
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    assert "tool:demo:echo" in ids
    assert "tool:calendar:query" not in ids


def test_super_admin_updates_exec_policy(
    super_admin: TenantContext, tool_reg: CapabilityRegistry
) -> None:
    with _client(super_admin, tool_reg) as client:
        r = client.put(
            "/api/admin/console/tools/tool:demo:echo/exec-policy",
            json={"timeout_s": 12, "max_retries": 2},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["exec_policy"]["timeout_s"] == 12
    assert body["exec_policy"]["max_retries"] == 2
    nested = tool_reg.get("tool:demo:echo", require_enabled=False).spec or {}
    assert nested.get("exec_policy", {}).get("timeout_s") == 12
