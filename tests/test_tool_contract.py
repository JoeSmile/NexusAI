"""Task 56 切片 1 — ToolContract 注册硬闸 + 治理链骨架。"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from packages.auth.models import TenantContext
from packages.capability.contract import (
    FailureSemantic,
    ToolContract,
    assert_contract_valid,
    derive_idempotency_key,
)
from packages.capability.errors import CapabilityContractError
from packages.capability.governance_chain import run_governance_chain
from packages.capability.invoke import _check_permission, invoke
from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)
from packages.capability.registry import CapabilityRegistry
from packages.errors import ErrorCode, NexusAIException


def _min_contract(cap_id: str, *, output_schema: dict | None = None) -> dict:
    return {
        "name": cap_id,
        "version": "v1",
        "description": "minimal valid tool contract for tests",
        "input_schema": {"type": "object"},
        "output_schema": output_schema
        if output_schema is not None
        else {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        "failure_semantics": {
            "retryable": True,
            "idempotent": True,
            "requires_compensation": False,
            "failure_codes": [],
        },
        "idempotency_key_args": ["q"],
        "examples": [{"input": {"q": "a"}, "output": {"ok": True}}],
    }


@pytest.fixture
def tenant_user() -> TenantContext:
    return TenantContext(
        tenant_id="t1",
        user_id="u1",
        role="user",
        extra_permissions=[],
        is_cross_tenant=False,
    )


def test_register_tool_without_contract_raises_cap_006() -> None:
    reg = CapabilityRegistry()
    with pytest.raises(CapabilityContractError) as ei:
        reg.register(
            CapabilitySpec(
                id="tool-bare",
                name="bare",
                kind=CapabilityKind.TOOL,
                provider=CapabilityProvider.NEXUSAI,
                permission="chat:write",
                spec={"governance": True},
            )
        )
    assert ei.value.code == ErrorCode.CAP_CONTRACT_INVALID.value
    assert "tool_contract_missing" in str(ei.value.detail)


def test_register_tool_missing_output_schema_raises() -> None:
    reg = CapabilityRegistry()
    raw = _min_contract("tool-no-out")
    raw["output_schema"] = {}
    with pytest.raises(CapabilityContractError) as ei:
        reg.register(
            CapabilitySpec(
                id="tool-no-out",
                name="no-out",
                kind=CapabilityKind.TOOL,
                provider=CapabilityProvider.NEXUSAI,
                permission="chat:write",
                spec={"governance": True, "tool_contract": raw},
            )
        )
    assert "missing_output_schema" in str(ei.value.detail)


def test_register_model_exempt_from_contract() -> None:
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="model:m",
            name="m",
            kind=CapabilityKind.MODEL,
            provider=CapabilityProvider.NEXUSAI,
            permission="chat:write",
        )
    )
    assert reg.get("model:m").contract is None


def test_register_tool_with_contract_ok() -> None:
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="hotspot.dig",
            name="热点",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            permission="chat:write",
            spec={
                "governance": True,
                "tool_contract": _min_contract("hotspot.dig"),
            },
        )
    )
    got = reg.get("hotspot.dig")
    assert got.contract is not None
    assert got.contract.failure_semantics.retryable is True
    assert got.contract.idempotency_key_args == ["q"]


def test_assert_contract_name_mismatch() -> None:
    from packages.capability.contract import ToolContractError

    c = ToolContract(
        name="other",
        description="long enough description here",
        output_schema={"type": "object"},
        examples=[{"input": {}, "output": {}}],
        failure_semantics=FailureSemantic(),
    )
    with pytest.raises(ToolContractError) as ei:
        assert_contract_valid(c, "mine")
    assert "name_mismatch" in str(ei.value)


def test_derive_idempotency_key() -> None:
    c = ToolContract(
        name="hotspot.dig",
        description="long enough description here",
        output_schema={"type": "object"},
        examples=[{"input": {}, "output": {}}],
        idempotency_key_args=["keywords"],
    )
    key = derive_idempotency_key(
        c, tenant_id="t1", payload={"keywords": "AI"}
    )
    assert key is not None
    assert "hotspot.dig" in key
    assert "AI" in key


def test_load_from_env_skips_bad_contract() -> None:
    reg = CapabilityRegistry()
    payload = json.dumps(
        [
            {
                "id": "bad-tool",
                "name": "bad",
                "kind": "tool",
                "provider": "nexusai",
                "permission": "chat:write",
                "governance": True,
            },
            {
                "id": "good-tool",
                "name": "good",
                "kind": "tool",
                "provider": "nexusai",
                "permission": "chat:write",
                "governance": True,
                "spec": {"tool_contract": _min_contract("good-tool")},
            },
        ]
    )
    n = reg.load_from_env(payload)
    assert n == 1
    assert reg.get("good-tool").id == "good-tool"
    from packages.capability.errors import CapabilityNotFoundError

    with pytest.raises(CapabilityNotFoundError):
        reg.get("bad-tool")


def test_governance_chain_approval_stub(tenant_user: TenantContext) -> None:
    spec = CapabilitySpec(
        id="gated",
        name="gated",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        permission="chat:write",
        spec={
            "governance": True,
            "requires_approval": True,
            "tool_contract": _min_contract("gated"),
        },
    )
    # bypass register — contract already on object for chain test
    from packages.capability.contract import parse_tool_contract

    spec.contract = parse_tool_contract(spec.spec["tool_contract"])
    with (
        patch("packages.capability.governance._redis", return_value=None),
        pytest.raises(NexusAIException) as ei,
    ):
        run_governance_chain(
            spec, tenant_user, {}, check_permission=_check_permission
        )
    assert ei.value.code == ErrorCode.CAP_GOVERNANCE_REQUIRED.value
    assert "approval_required" in ei.value.message
    detail = json.loads(str(ei.value.detail))
    assert detail["reason"] == "approval_required"


@pytest.mark.asyncio
async def test_invoke_runs_governance_without_sse_pollution(
    tenant_user: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
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
    with (
        patch(
            "packages.capability.invoke.get_capability_registry",
            return_value=reg,
        ),
        patch("packages.capability.governance._redis", return_value=None),
    ):
        frames: list[dict] = []
        async for f in invoke(
            "model:mock-local", {"message": "hello"}, tenant_user
        ):
            frames.append(f)
    assert any(f.get("event") == "done" for f in frames)
    assert all(f.get("event") != "governance" for f in frames)
