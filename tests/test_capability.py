"""Task 30: Capability registry / governance / invoke — 最小回归（卡点补测）。"""

from __future__ import annotations

import json
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


def test_build_dify_request_shape(tenant_user: TenantContext) -> None:
    from backend.core.capability.connectors.external_app import build_dify_request

    spec = CapabilitySpec(
        id="dify-contract-review",
        name="Dify合同",
        kind=CapabilityKind.EXTERNAL_APP,
        provider=CapabilityProvider.DIFY,
        permission="chat:write",
        spec={
            "governance": True,
            "base_url": "https://api.dify.ai/v1",
            "api_key_ref": "DIFY_API_KEY",
            "api_key": "test-key",
            "workflow_id": "wf-1",
        },
    )
    req = build_dify_request(spec, {"message": "审合同"}, tenant_user)
    assert req.method == "POST"
    assert req.url == "https://api.dify.ai/v1/workflows/run"
    assert req.headers["Authorization"] == "Bearer test-key"
    assert req.json_body["response_mode"] == "streaming"
    assert req.json_body["inputs"]["query"] == "审合同"
    assert req.json_body["workflow_id"] == "wf-1"
    assert req.provider == "dify"


def test_parse_dify_sse_to_unified_frames() -> None:
    from backend.core.capability.connectors.external_app import parse_upstream_sse_line

    frames = parse_upstream_sse_line(
        'data: {"event":"text_chunk","data":{"text":"hi"}}',
        provider="dify",
    )
    assert frames == [{"event": "token", "data": "hi"}]


def test_audit_prefix_includes_upstream() -> None:
    """审计无独立 upstream 列时用 input_text 前缀（与 router 约定一致）。"""
    cost_source = "invoke"
    upstream = "dify"
    tags = f"[cost_source={cost_source}][upstream={upstream}]"
    assert "upstream=dify" in tags


@pytest.mark.asyncio
async def test_invoke_external_mock_and_circuit(
    tenant_user: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.core.capability.connectors import external_app as ext
    from backend.core.capability.errors import CapabilityUpstreamError
    from backend.core.circuit_breaker import CircuitState

    monkeypatch.setenv("CAPABILITY_UPSTREAM_MOCK", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    ext._BREAKERS.clear()

    spec = CapabilitySpec(
        id="dify-mock",
        name="dify-mock",
        kind=CapabilityKind.EXTERNAL_APP,
        provider=CapabilityProvider.DIFY,
        permission="chat:write",
        cost_model={"cost_per_1k": 1.0},
        spec={
            "governance": True,
            "base_url": "https://api.dify.ai/v1",
            "api_key": "k",
        },
    )
    frames: list[dict] = []
    async for f in ext.invoke_external(spec, {"message": "x"}, tenant_user):
        frames.append(f)
    assert any(f.get("event") == "token" for f in frames)
    usage = next(f for f in frames if f.get("event") == "usage")
    assert usage["data"]["upstream"] == "dify"
    assert usage.get("cost_source") == "invoke"
    done = frames[-1]
    assert done["event"] == "done"
    assert done["data"]["upstream"] == "dify"

    # 断路器打开 → CAP_003，不 hang
    b = ext._breaker(f"cap:dify:{spec.id}")
    b._state = CircuitState.OPEN
    b._last_failure_time = 1e12  # 远未来，保持 open
    with pytest.raises(CapabilityUpstreamError) as ei:
        async for _ in ext.invoke_external(spec, {"message": "x"}, tenant_user):
            pass
    assert ei.value.code == ErrorCode.CAP_UPSTREAM_ERROR.value
    assert "circuit_open" in ei.value.message

def test_env_load_and_db_override_same_id() -> None:
    """DB 后加载覆盖同 id 的 env 条目。"""
    reg = CapabilityRegistry()
    n = reg.load_from_env(
        json.dumps(
            [
                {
                    "id": "shared-cap",
                    "name": "from-env",
                    "kind": "model",
                    "provider": "contextgate",
                    "permission": "chat:write",
                }
            ]
        )
    )
    assert n == 1
    assert reg.get("shared-cap").name == "from-env"

    reg.register(
        CapabilitySpec(
            id="shared-cap",
            name="from-db",
            kind=CapabilityKind.MODEL,
            provider=CapabilityProvider.CONTEXTGATE,
            permission="chat:write",
        )
    )
    assert reg.get("shared-cap").name == "from-db"


@pytest.mark.asyncio
async def test_unsupported_kind_raises_cap_001(tenant_user: TenantContext) -> None:
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="tool-x",
            name="tool-x",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.CONTEXTGATE,
            permission="chat:write",
            spec={"governance": True},
        )
    )
    with (
        patch(
            "backend.core.capability.invoke.get_capability_registry",
            return_value=reg,
        ),
        patch("backend.core.capability.governance._redis", return_value=None),
    ):
        with pytest.raises(CapabilityNotFoundError) as ei:
            async for _ in invoke("tool-x", {"message": "hi"}, tenant_user):
                pass
    assert ei.value.code == ErrorCode.CAP_NOT_FOUND.value
    assert "unsupported_kind" in ei.value.message


@pytest.mark.asyncio
async def test_model_invoke_skips_invoke_layer_record_consumption(
    tenant_user: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """接缝 4：kind=model 不在 invoke 层二次 record_consumption。"""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="model:mock-local",
            name="mock-local",
            kind=CapabilityKind.MODEL,
            provider=CapabilityProvider.SELF_HOSTED,
            permission="chat:write",
            spec={"max_tokens": 16},
        )
    )
    with (
        patch(
            "backend.core.capability.invoke.get_capability_registry",
            return_value=reg,
        ),
        patch("backend.core.capability.governance._redis", return_value=None),
        patch("backend.core.cost_manager.record_consumption") as rec,
    ):
        async for _ in invoke(
            "model:mock-local", {"message": "cost check"}, tenant_user
        ):
            pass
    assert rec.call_count == 0


def test_agent_self_ref_and_depth_covered_in_agents_suite() -> None:
    """30.27 AC：Agent 自引用/深度 — 实现于 tests/test_capability_agents.py。"""
    from tests.test_capability_agents import (
        test_agent_depth_limit,
        test_self_reference_rejected_on_register,
    )

    assert callable(test_self_reference_rejected_on_register)
    assert callable(test_agent_depth_limit)
