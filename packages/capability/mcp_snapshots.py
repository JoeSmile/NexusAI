"""Versioned MCP tool snapshots — retire without breaking in-flight calls (Task 66 Phase 2)."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from packages.capability.errors import CapabilityNotFoundError
from packages.capability.models import CapabilityStatus
from packages.capability.registry import CapabilityRegistry

logger = logging.getLogger(__name__)

_SNAPSHOT = None


class McpSnapshotRegistry:
    """Tracks per-server generations; disables removed tools instead of deleting."""

    def __init__(self) -> None:
        self._server_generation: dict[str, int] = {}
        self._active_generation: dict[str, int] = {}  # cap_id -> generation

    def refresh_server_tools(
        self,
        registry: CapabilityRegistry,
        server_id: str,
        tools: list[dict[str, Any]],
        *,
        normalize_fn,
        server_cfg,
    ) -> dict[str, Any]:
        generation = self._server_generation.get(server_id, 0) + 1
        self._server_generation[server_id] = generation

        registered = 0
        rejected = 0
        seen: set[str] = set()
        prefix = f"mcp:{server_id}:"

        for tool in tools:
            if not isinstance(tool, dict):
                rejected += 1
                continue
            try:
                spec = normalize_fn(server_cfg, tool, snapshot_generation=generation)
            except Exception as exc:
                logger.warning("mcp tool normalize failed: %s", exc)
                rejected += 1
                continue
            if spec is None:
                rejected += 1
                continue
            try:
                registry.register(spec)
                self._active_generation[spec.id] = generation
                seen.add(spec.id)
                registered += 1
            except Exception as exc:
                logger.warning("mcp tool register failed %s: %s", spec.id, exc)
                rejected += 1

        retired = 0
        for cap_id, active_gen in list(self._active_generation.items()):
            if not cap_id.startswith(prefix) or cap_id in seen:
                continue
            if self._retire_tool(registry, cap_id, active_gen):
                retired += 1
            self._active_generation.pop(cap_id, None)

        return {
            "generation": generation,
            "registered": registered,
            "rejected": rejected,
            "retired": retired,
            "active_tools": sorted(seen),
        }

    @staticmethod
    def _retire_tool(
        registry: CapabilityRegistry, cap_id: str, generation: int
    ) -> bool:
        try:
            spec = registry.get(cap_id, require_enabled=False)
        except CapabilityNotFoundError:
            return False
        nested = dict(spec.spec or {})
        nested["mcp_retired"] = True
        nested["mcp_retired_generation"] = generation
        nested["mcp_snapshot_generation"] = generation
        retired = replace(
            spec,
            status=CapabilityStatus.DISABLED,
            spec=nested,
        )
        try:
            registry.register(retired)
            return True
        except Exception as exc:
            logger.warning("mcp retire failed %s: %s", cap_id, exc)
            return False


def get_mcp_snapshot_registry() -> McpSnapshotRegistry:
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = McpSnapshotRegistry()
    return _SNAPSHOT


def reset_mcp_snapshot_registry_for_tests() -> None:
    global _SNAPSHOT
    _SNAPSHOT = McpSnapshotRegistry()
