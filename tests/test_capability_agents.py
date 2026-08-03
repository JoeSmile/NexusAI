"""Task 30.24 — Agent 门面：自引用拒绝、深度上限、嵌套链。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.core.auth.models import TenantContext
from backend.core.capability.agents import MAX_AGENT_DEPTH, invoke_agent
from backend.core.capability.errors import (
    CapabilityGovernanceRequiredError,
    CapabilityUpstreamError,
)
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)
from backend.core.capability.registry import CapabilityRegistry
from backend.core.errors import ErrorCode


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext("t1", "u1", "user", [], False)


def _agent(cap_id: str, caps: list[str]) -> CapabilitySpec:
    return CapabilitySpec(
        id=cap_id,
        name=cap_id,
        kind=CapabilityKind.AGENT,
        provider=CapabilityProvider.CONTEXTGATE,
        permission="chat:write",
        spec={"governance": True, "capabilities": caps},
    )


def _leaf(cap_id: str, *, chain_audit: bool = True) -> CapabilitySpec:
    return CapabilitySpec(
        id=cap_id,
        name=cap_id,
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.CONTEXTGATE,
        permission="chat:write",
        spec={"governance": True, "leaf": True, "chain_audit": chain_audit},
    )


def test_self_reference_rejected_on_register() -> None:
    reg = CapabilityRegistry()
    with pytest.raises(CapabilityGovernanceRequiredError) as ei:
        reg.register(_agent("self-agent", ["self-agent"]))
    assert ei.value.code == ErrorCode.CAP_GOVERNANCE_REQUIRED.value
    assert "self" in (ei.value.message or "")


@pytest.mark.asyncio
async def test_vendor_risk_call_chain_and_audits(tenant: TenantContext) -> None:
    reg = CapabilityRegistry()
    for spec in (
        _leaf("rag-ask"),
        _leaf("contextgate-chat", chain_audit=False),
        _agent("contract-query-agent", ["rag-ask", "contextgate-chat"]),
        _agent("vendor-risk-agent", ["contract-query-agent", "contextgate-chat"]),
    ):
        reg.register(spec)

    audits: list[str] = []

    def fake_audit(record: dict) -> None:
        audits.append(str(record.get("model")))

    async def fake_process(*_a, **_k):
        return {"success": True, "data": {"response": "risk-ok"}}

    with (
        patch(
            "backend.core.capability.registry.get_capability_registry",
            return_value=reg,
        ),
        patch("backend.core.audit.write_audit_sync", side_effect=fake_audit),
        patch(
            "backend.services.agent_service.get_agent_service",
            return_value=type(
                "S",
                (),
                {"process_message": AsyncMock(side_effect=fake_process)},
            )(),
        ),
    ):
        frames = []
        async for f in invoke_agent(
            reg.get("vendor-risk-agent"),
            {"message": "评估供应商风险"},
            tenant,
        ):
            frames.append(f)

    assert any(f.get("event") == "token" for f in frames)
    done = next(f for f in frames if f.get("event") == "done")
    assert done["data"]["call_chain"] == [
        "vendor-risk-agent",
        "contract-query-agent",
        "rag-ask",
    ]
    assert audits == [
        "vendor-risk-agent",
        "contract-query-agent",
        "rag-ask",
    ]


@pytest.mark.asyncio
async def test_non_leaf_child_uses_real_invoke(tenant: TenantContext) -> None:
    """无 leaf 标记时走 invoke()，不合成 stub 文案。"""
    reg = CapabilityRegistry()
    model = CapabilitySpec(
        id="model:mock-local",
        name="mock-local",
        kind=CapabilityKind.MODEL,
        provider=CapabilityProvider.SELF_HOSTED,
        permission="chat:write",
        spec={"max_tokens": 16},
    )
    reg.register(model)
    reg.register(_agent("wrap-model", ["model:mock-local"]))

    with (
        patch(
            "backend.core.capability.registry.get_capability_registry",
            return_value=reg,
        ),
        patch("backend.core.capability.governance._redis", return_value=None),
        patch("backend.core.audit.write_audit_sync"),
        patch(
            "backend.services.agent_service.get_agent_service",
            return_value=type(
                "S",
                (),
                {
                    "process_message": AsyncMock(
                        return_value={"success": True, "data": {"response": "wrap"}}
                    )
                },
            )(),
        ),
    ):
        import os

        os.environ["LLM_PROVIDER"] = "mock"
        frames: list[dict] = []
        async for f in invoke_agent(
            reg.get("wrap-model"), {"message": "hello model"}, tenant
        ):
            frames.append(f)
    tokens = "".join(
        str(f.get("data") or "") for f in frames if f.get("event") == "token"
    )
    assert "[model:mock-local] processed:" not in tokens
    assert any(f.get("event") == "done" for f in frames)


@pytest.mark.asyncio
async def test_agent_depth_limit(tenant: TenantContext) -> None:
    reg = CapabilityRegistry()
    # a0 → a1 → a2 → a3（第 4 层应拒绝）
    reg.register(_leaf("rag-ask"))
    reg.register(_agent("a3", ["rag-ask"]))
    reg.register(_agent("a2", ["a3"]))
    reg.register(_agent("a1", ["a2"]))
    reg.register(_agent("a0", ["a1"]))

    with (
        patch(
            "backend.core.capability.registry.get_capability_registry",
            return_value=reg,
        ),
        patch("backend.core.audit.write_audit_sync"),
        patch(
            "backend.services.agent_service.get_agent_service",
            return_value=type(
                "S",
                (),
                {
                    "process_message": AsyncMock(
                        return_value={"success": True, "data": {"response": "x"}}
                    )
                },
            )(),
        ),
    ):
        with pytest.raises(CapabilityUpstreamError) as ei:
            async for _ in invoke_agent(
                reg.get("a0"), {"message": "deep"}, tenant
            ):
                pass
    assert "depth" in ei.value.message
    assert str(MAX_AGENT_DEPTH) in (ei.value.detail or "")
