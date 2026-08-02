"""Capability 层 — 统一能力模型与错误码（Task 30）。"""

from backend.core.capability.errors import (
    CapabilityDisabledError,
    CapabilityGovernanceRequiredError,
    CapabilityNotFoundError,
    CapabilityQuotaExceededError,
    CapabilityUpstreamError,
)
from backend.core.capability.governance import (
    check_cap_quota,
    check_cap_rate_limit,
    validate_governance_declaration,
)
from backend.core.capability.invoke import invoke
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from backend.core.capability.registry import (
    CapabilityRegistry,
    get_cap_quota_daily_calls,
    get_cap_quota_daily_cost_usd,
    get_capability_registry,
    model_spec_to_capability,
    reload_capability_registry,
    resolve_credential,
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
    "check_cap_quota",
    "check_cap_rate_limit",
    "get_cap_quota_daily_calls",
    "get_cap_quota_daily_cost_usd",
    "get_capability_registry",
    "invoke",
    "model_spec_to_capability",
    "reload_capability_registry",
    "resolve_credential",
    "validate_governance_declaration",
]
