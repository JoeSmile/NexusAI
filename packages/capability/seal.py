"""Dify / Coze / kind=external_app 已封。对话与工具只走本平台。"""

from __future__ import annotations

from packages.capability.errors import CapabilityDisabledError
from packages.capability.models import CapabilityKind, CapabilityProvider, CapabilitySpec

_SEALED_PROVIDERS = frozenset({CapabilityProvider.DIFY, CapabilityProvider.COZE})


def is_external_agent_sealed(spec: CapabilitySpec) -> bool:
    if spec.kind == CapabilityKind.EXTERNAL_APP:
        return True
    return getattr(spec, "provider", None) in _SEALED_PROVIDERS


def reject_sealed_external_agent(spec: CapabilitySpec) -> None:
    if not is_external_agent_sealed(spec):
        return
    kind = spec.kind.value if hasattr(spec.kind, "value") else str(spec.kind)
    provider = spec.provider.value if hasattr(spec.provider, "value") else str(spec.provider)
    raise CapabilityDisabledError(
        message="external_agent_sealed",
        detail=f"{spec.id}:{kind}:{provider}",
    )
