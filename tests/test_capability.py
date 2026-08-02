"""Task 30: Capability registry / governance / invoke — 最小回归（卡点补测）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.auth.models import TenantContext
from backend.core.capability.errors import (
    CapabilityDisabledError,
    CapabilityGovernanceRequiredError,
    CapabilityNotFoundError,
    CapabilityQuotaExceededError,
)
from backend.core.capability.governance import check_cap_quota, validate_governance_declaration
from backend.core.capability.invoke import invoke
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from backend.core.capability.registry import CapabilityRegistry
from backend.core.errors import ContextGateException, ErrorCode


@pytest.fixture
def tenant_user() -> TenantContext:
    return TenantContext(
        tenant_id="t1",
        user_id="u1",
        role="user",
        extra_permissions=[],
        is_cross_tenant=False,
    )


def test_register_non_model_without_governance_raises_cap_004() -> None:
    reg = CapabilityRegistry()
    with pytest.raises(CapabilityGovernanceRequiredError) as ei:
        reg.register(
            CapabilitySpec(
                id="ext-bad",
                name="bad",
                kind=CapabilityKind.EXTERNAL_APP,
                provider=CapabilityProvider.DIFY,
                permission="chat:write",
            )
        )
    assert ei.value.code == ErrorCode.CAP_GOVERNANCE_REQUIRED.value


def test_validate_governance_model_exempt() -> None:
    validate_governance_declaration(
        CapabilitySpec(
            id="model:m",
            name="m",
            kind=CapabilityKind.MODEL,
            provider=CapabilityProvider.CONTEXTGATE,
        )
    )


def test_get_missing_and_disabled() -> None:
    reg = CapabilityRegistry()
    with pytest.raises(CapabilityNotFoundError) as e1:
        reg.get("nope")
    assert e1.value.code == ErrorCode.CAP_NOT_FOUND.value

    reg.register(
        CapabilitySpec(
            id="off",
            name="off",
            kind=CapabilityKind.MODEL,
            provider=CapabilityProvider.CONTEXTGATE,
            status=CapabilityStatus.DISABLED,
            permission="chat:write",
        )
    )
    with pytest.raises(CapabilityDisabledError) as e2:
        reg.get("off")
    assert e2.value.code == ErrorCode.CAP_DISABLED.value


def test_quota_exceeded_cap_005(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeR:
        def get(self, key: str):
            if "calls" in key:
                return "100"
            return "0"

    monkeypatch.setenv("CAP_QUOTA_DAILY_CALLS", "10")
    monkeypatch.setenv("CAP_QUOTA_DAILY_COST_USD", "10.0")
    try:
        from config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass

    with (
        patch("backend.core.capability.governance._redis", return_value=FakeR()),
        patch("backend.core.capability.governance._day_bucket", return_value="20260101"),
    ):
        with pytest.raises(CapabilityQuotaExceededError) as ei:
            check_cap_quota("t1")
    assert ei.value.code == ErrorCode.CAP_QUOTA_EXCEEDED.value


@pytest.mark.asyncio
async def test_invoke_model_stream_and_auth(
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
    # Redis 不可用 = fail-open（拍板 A）；测分发/鉴权不依赖 Redis
    with (
        patch(
            "backend.core.capability.invoke.get_capability_registry",
            return_value=reg,
        ),
        patch("backend.core.capability.governance._redis", return_value=None),
    ):
        auditor = TenantContext("t1", "a1", "auditor", [], True)
        with pytest.raises(ContextGateException) as ei:
            async for _ in invoke("model:mock-local", {"message": "hi"}, auditor):
                pass
        assert ei.value.code == ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS.value

        with pytest.raises(ContextGateException) as e2:
            async for _ in invoke("model:mock-local", {}, tenant_user):
                pass
        assert e2.value.code == ErrorCode.REQ_INVALID.value

        frames: list[dict] = []
        async for f in invoke(
            "model:mock-local", {"message": "hello cap"}, tenant_user
        ):
            frames.append(f)
        assert any(f.get("event") == "token" for f in frames)
        assert frames[-1].get("event") == "done"
        assert all(
            f.get("cost_source") == "harness" for f in frames if "cost_source" in f
        )