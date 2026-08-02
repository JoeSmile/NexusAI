"""Capability 层 — 统一能力模型与错误码（Task 30）。"""

from backend.core.capability.errors import (
    CapabilityDisabledError,
    CapabilityGovernanceRequiredError,
    CapabilityNotFoundError,
    CapabilityQuotaExceededError,
    CapabilityUpstreamError,
)
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from backend.core.capability.registry import (
    CapabilityRegistry,
    get_capability_registry,
    model_spec_to_capability,
    reload_capability_registry,
)

__all__ = [
    "CapabilityDisabledError",
    "CapabilityGovernanceRequiredError",
    "CapabilityKind",
    "CapabilityNotFoundError",
    "CapabilityProvider",
    "CapabilityQuotaExceededError",
    "CapabilityRegistry",
    "CapabilitySpec",
    "CapabilityStatus",
    "CapabilityUpstreamError",
    "get_capability_registry",
    "model_spec_to_capability",
    "reload_capability_registry",
]
