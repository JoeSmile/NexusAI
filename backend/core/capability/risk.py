"""Capability risk level helpers (Task 62 slice 2)."""

from __future__ import annotations

from backend.core.capability.models import CapabilitySpec

_CRITICAL_LEVELS = frozenset({"critical"})


def capability_risk_level(spec: CapabilitySpec) -> str:
    raw = spec.spec if isinstance(spec.spec, dict) else {}
    return str(raw.get("risk_level") or "low").strip().lower()


def is_critical_capability(spec: CapabilitySpec) -> bool:
    return capability_risk_level(spec) in _CRITICAL_LEVELS
