"""Task 66 slice 1 — builtin tools registration and invoke."""

from __future__ import annotations

import pytest

from packages.auth.models import TenantContext
from backend.core.capability.builtin.register import register_builtin_tools
from backend.core.capability.builtin.specs import BUILTIN_TOOL_SPECS
from backend.core.capability.contract import validate_capability_contract
from backend.core.capability.exec_policy import global_default_exec_policy, resolve_exec_policy
from backend.core.capability.governance_chain import run_governance_chain
from backend.core.capability.models import CapabilityKind, CapabilitySpec
from backend.core.capability.registry import CapabilityRegistry
from backend.core.errors import ErrorCode, NexusAIException


@pytest.fixture
def tenant_user() -> TenantContext:
    return TenantContext(
        tenant_id="t-builtin",
        user_id="u1",
        role="user",
        extra_permissions=["chat:write", "memory:read", "memory:write"],
        is_cross_tenant=False,
    )


def test_builtin_specs_have_valid_contracts() -> None:
    for raw in BUILTIN_TOOL_SPECS:
        spec = CapabilitySpec(
            id=str(raw["id"]),
            name=str(raw.get("name") or raw["id"]),
            kind=CapabilityKind.TOOL,
            provider=raw.get("provider", "nexusai"),  # type: ignore[arg-type]
            spec=dict(raw.get("spec") or {}),
            permission=str(raw.get("permission") or "chat:write"),
        )
        validate_capability_contract(spec)
        assert spec.contract is not None
        assert spec.contract.name == spec.id


def test_register_builtin_tools_count() -> None:
    reg = CapabilityRegistry()
    n = register_builtin_tools(reg)
    assert n == len(BUILTIN_TOOL_SPECS)
    for raw in BUILTIN_TOOL_SPECS:
        spec = reg.get(str(raw["id"]))
        assert spec.kind == CapabilityKind.TOOL
        assert spec.spec.get("executor") == "builtin"


def test_register_builtin_skips_existing() -> None:
    reg = CapabilityRegistry()
    first = register_builtin_tools(reg)
    second = register_builtin_tools(reg)
    assert first == len(BUILTIN_TOOL_SPECS)
    assert second == 0


def test_exec_policy_defaults_and_override() -> None:
    base = global_default_exec_policy()
    assert base.timeout_s > 0
    overridden = resolve_exec_policy({"exec_policy": {"timeout_s": 5}})
    assert overridden.timeout_s == 5
    assert overridden.max_retries == base.max_retries


@pytest.mark.asyncio
async def test_invoke_calendar_query_handler(tenant_user: TenantContext) -> None:
    from backend.core.capability.builtin.handlers import invoke_builtin_handler

    result = await invoke_builtin_handler(
        "calendar.query",
        {"from": "2026-01-01", "to": "2026-01-07"},
        tenant_user,
    )
    assert result.get("ok") is True
    assert (result.get("data") or {}).get("from") == "2026-01-01"


@pytest.mark.asyncio
async def test_sql_query_rejects_mutating(tenant_user: TenantContext) -> None:
    from backend.core.capability.builtin.handlers import invoke_builtin_handler

    result = await invoke_builtin_handler(
        "sql.query",
        {"sql": "delete from users"},
        tenant_user,
    )
    assert result.get("ok") is False


def test_governance_denies_mail_send_without_approval(tenant_user: TenantContext) -> None:
    from backend.core.capability.invoke import _check_permission

    reg = CapabilityRegistry()
    register_builtin_tools(reg)
    spec = reg.get("mail.send")
    with pytest.raises(NexusAIException) as exc:
        run_governance_chain(spec, tenant_user, {}, check_permission=_check_permission)
    assert exc.value.code == ErrorCode.CAP_GOVERNANCE_REQUIRED.value


def test_governance_allows_calendar_query(tenant_user: TenantContext) -> None:
    from backend.core.capability.invoke import _check_permission

    reg = CapabilityRegistry()
    register_builtin_tools(reg)
    spec = reg.get("calendar.query")
    explain = run_governance_chain(spec, tenant_user, {}, check_permission=_check_permission)
    assert explain.allowed is True


@pytest.mark.asyncio
async def test_web_search_ssrf_blocks_localhost(tenant_user: TenantContext) -> None:
    from backend.core.capability.builtin.handlers import invoke_builtin_handler

    result = await invoke_builtin_handler(
        "web.search",
        {"query": "test", "url": "http://localhost/admin"},
        tenant_user,
    )
    assert result.get("ok") is False
