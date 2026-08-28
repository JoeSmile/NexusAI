"""Wave C0 — capability param_spec 落地。"""

from __future__ import annotations

from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from packages.capability.registry import CapabilityRegistry
from apps.api.routers.capability import _spec_public


def test_capability_spec_accepts_param_spec() -> None:
    ps = {
        "query": {"type": "string", "required": True, "description": "q"},
        "search_k": {"type": "number", "required": False, "default": 3},
    }
    spec = CapabilitySpec(
        id="rag-ask",
        name="RAG Ask",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={"governance": True, "leaf": True, "executor": "rag"},
        permission="chat:write",
        param_spec=ps,
    )
    assert spec.param_spec == ps


def test_spec_public_exposes_param_spec() -> None:
    spec = CapabilitySpec(
        id="rag-ask",
        name="RAG Ask",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={"governance": True},
        param_spec={"query": {"type": "string", "required": True}},
    )
    pub = _spec_public(spec)
    assert pub["param_spec"] == {"query": {"type": "string", "required": True}}


def test_spec_public_null_param_spec() -> None:
    spec = CapabilitySpec(
        id="agent-x",
        name="Agent",
        kind=CapabilityKind.AGENT,
        provider=CapabilityProvider.NEXUSAI,
        spec={"governance": True, "capabilities": []},
        status=CapabilityStatus.ENABLED,
    )
    pub = _spec_public(spec)
    assert pub["param_spec"] is None


def test_env_load_parses_param_spec() -> None:
    reg = CapabilityRegistry()
    raw = """
    [{
      "id": "tool-ps",
      "name": "Tool PS",
      "kind": "tool",
      "provider": "nexusai",
      "permission": "chat:write",
      "spec": {"governance": true, "leaf": true},
      "param_spec": {
        "message": {"type": "string", "required": true}
      }
    }]
    """
    n = reg.load_from_env(raw)
    assert n == 1
    got = reg.get("tool-ps")
    assert got is not None
    assert got.param_spec == {"message": {"type": "string", "required": True}}


def test_register_without_param_spec_still_ok() -> None:
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="plain",
            name="Plain",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True},
            permission="chat:write",
        )
    )
    assert reg.get("plain") is not None
    assert reg.get("plain").param_spec is None


def test_tenant_list_payload_shape_has_param_spec_key() -> None:
    """编辑器依赖 list 响应含 param_spec 键（可为 null）。"""
    pub = _spec_public(
        CapabilitySpec(
            id="x",
            name="X",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True},
        )
    )
    assert "param_spec" in pub
    assert pub["param_spec"] is None
