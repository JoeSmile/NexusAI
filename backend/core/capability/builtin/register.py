"""Register builtin tools into CapabilityRegistry."""

from __future__ import annotations

import logging

from backend.core.capability.builtin.specs import BUILTIN_TOOL_SPECS
from backend.core.capability.errors import CapabilityNotFoundError
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from backend.core.capability.registry import CapabilityRegistry

logger = logging.getLogger(__name__)


def builtin_raw_to_spec(raw: dict) -> CapabilitySpec:
    return CapabilitySpec(
        id=str(raw["id"]),
        name=str(raw.get("name") or raw["id"]),
        kind=CapabilityKind(str(raw["kind"])),
        provider=CapabilityProvider(str(raw.get("provider", CapabilityProvider.NEXUSAI.value))),
        spec=dict(raw.get("spec") or {}),
        status=CapabilityStatus.ENABLED,
        permission=str(raw.get("permission") or ""),
    )


def register_builtin_tools(registry: CapabilityRegistry) -> int:
    """Register in-memory builtin tools; skip ids already present."""
    count = 0
    for raw in BUILTIN_TOOL_SPECS:
        cap_id = str(raw["id"])
        try:
            registry.get(cap_id, require_enabled=False)
            continue
        except CapabilityNotFoundError:
            pass
        registry.register(builtin_raw_to_spec(raw))
        count += 1
    logger.info(
        "registered %s builtin tools (%s skipped)",
        count,
        len(BUILTIN_TOOL_SPECS) - count,
    )
    return count
