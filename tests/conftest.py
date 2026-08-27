"""Test defaults: do not spam OTLP to local Langfuse during unit tests."""

from __future__ import annotations

import os

# Strong JWT before backend.app import (Task 59 S6 startup check)
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-wave-a-min-32-bytes!!")

import pytest


@pytest.fixture(autouse=True)
def _ssrf_default_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests default-deny loopback; opt in with SSRF_ALLOW_LOCAL_DEV in the test."""
    monkeypatch.delenv("SSRF_ALLOW_LOCAL_DEV", raising=False)


@pytest.fixture(scope="session", autouse=True)
def _quiet_langfuse_unless_requested():
    if os.getenv("LANGFUSE_IN_TESTS", "").strip() in {"1", "true", "yes"}:
        yield
        return
    prev = {k: os.environ.get(k) for k in (
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "LANGFUSE_BASE_URL",
    )}
    os.environ["LANGFUSE_ENABLED"] = "0"
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    # Reset singleton if already warmed by import
    try:
        import backend.observability.langfuse_client as lf

        lf._lf = None
        lf._init_attempted = False
    except Exception:
        pass
    yield
    for k, v in prev.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def _autofill_tool_contracts(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
):
    """存量单测未带 ToolContract 时自动补 stub；``test_tool_contract`` 测硬闸时跳过。"""
    if "test_tool_contract" in request.node.nodeid:
        yield
        return

    from backend.core.capability.contract import (
        contract_required_for,
        stub_contract_dict,
    )
    from backend.core.capability.registry import CapabilityRegistry

    original = CapabilityRegistry.register

    def _register(self: CapabilityRegistry, spec):  # type: ignore[no-untyped-def]
        if contract_required_for(spec.kind):
            nested = dict(spec.spec or {})
            if "tool_contract" not in nested:
                nested["tool_contract"] = stub_contract_dict(spec.id)
                spec.spec = nested
        return original(self, spec)

    monkeypatch.setattr(CapabilityRegistry, "register", _register)
    yield
