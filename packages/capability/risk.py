"""Capability risk level helpers (Task 62 slice 2)."""

from __future__ import annotations

from packages.capability.models import CapabilitySpec

_SUB_AGENT_BLOCKED_LEVELS = frozenset({"critical", "high"})


def capability_risk_level(spec: CapabilitySpec) -> str:
    raw = spec.spec if isinstance(spec.spec, dict) else {}
    return str(raw.get("risk_level") or "low").strip().lower()


def is_sub_agent_blocked_capability(spec: CapabilitySpec) -> bool:
    """Sub-agents may not invoke critical or high risk capabilities (Task 62 拍板 B)."""
    return capability_risk_level(spec) in _SUB_AGENT_BLOCKED_LEVELS


def is_critical_capability(spec: CapabilitySpec) -> bool:
    """Deprecated alias — use is_sub_agent_blocked_capability."""
    return is_sub_agent_blocked_capability(spec)
