"""Test defaults: do not spam OTLP to local Langfuse during unit tests."""

from __future__ import annotations

import os

# Strong JWT before apps.api.app import (Task 59 S6 startup check)
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-wave-a-min-32-bytes!!")

# Test default: NEVER hit real LLM APIs during unit tests.
# provider is resolved per-call (get_llm_provider), but config.env (loaded on package
# import) sets LLM_PROVIDER=openai + real keys. Neutralize here, before any
# packages.* import, so a bare `uv run pytest` stays offline and free.
# Escape hatches (any of these -> conftest does NOT lock provider/keys):
#   RUN_S4_GOLDEN_LAB=1        golden lab live eval (user explicitly wants real calls)
#   LLM_PROVIDER=<...>         explicit env (CI integration tests)
#   TEST_LLM_PROVIDER=<...>    per-invocation override
_LAB_RUN = os.getenv("RUN_S4_GOLDEN_LAB", "").strip().lower() in ("1", "true", "yes")
_EXPLICIT_PROVIDER = bool(
    os.getenv("LLM_PROVIDER") or os.getenv("TEST_LLM_PROVIDER")
)
if not _LAB_RUN and not _EXPLICIT_PROVIDER:
    # 空串占位而非 pop:config.py load_dotenv(override=False) 只注入缺失变量,
    # 空值可阻止真实 key 在后续 import 时被重新灌入。
    os.environ["LLM_PROVIDER"] = os.environ.get("TEST_LLM_PROVIDER", "mock")
    for _k in (
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "QWEN_API_KEY",
        "DASHSCOPE_API_KEY",
    ):
        os.environ[_k] = ""

import pytest


@pytest.fixture(autouse=True)
def _clear_run_registries():
    """每用例清空进程级 run 注册表（run_cancel / event_bus），防跨用例串扰。"""
    yield
    from packages.plan import event_bus as _eb
    from packages.plan import run_cancel as _rc
    from packages.plan import run_registry as _rr

    _rc._active.clear()
    _rc._cancelled.clear()
    _eb._RUN_BUSES.clear()
    _rr._runs.clear()


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
        import packages.observability.langfuse_client as lf

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

    from packages.capability.contract import (
        contract_required_for,
        stub_contract_dict,
    )
    from packages.capability.registry import CapabilityRegistry

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
