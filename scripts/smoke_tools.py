#!/usr/bin/env python3
"""Smoke builtin tools — list registration and dry-run one handler (Task 66 slice 1)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packages.auth.models import TenantContext
from backend.core.capability.builtin.handlers import invoke_builtin_handler
from backend.core.capability.builtin.register import register_builtin_tools
from backend.core.capability.builtin.specs import BUILTIN_TOOL_SPECS
from backend.core.capability.registry import CapabilityRegistry


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id=os.getenv("SMOKE_TENANT", "default"),
        user_id=os.getenv("SMOKE_USER", "smoke"),
        role="user",
        extra_permissions=["chat:write", "memory:read", "memory:write", "rag:read"],
        is_cross_tenant=False,
    )


def list_tools() -> None:
    reg = CapabilityRegistry()
    register_builtin_tools(reg)
    ids = sorted(str(raw["id"]) for raw in BUILTIN_TOOL_SPECS)
    print(f"builtin tools defined: {len(ids)}")
    for cap_id in ids:
        spec = reg.get(cap_id)
        risk = (spec.spec or {}).get("risk_level", "?")
        print(f"  - {cap_id} risk={risk} permission={spec.permission or '-'}")


async def dry_run(tool_id: str, payload_json: str | None) -> None:
    reg = CapabilityRegistry()
    register_builtin_tools(reg)
    reg.get(tool_id)
    payload: dict = {}
    if payload_json:
        payload = json.loads(payload_json)
    if tool_id == "calendar.query" and not payload:
        payload = {"from": "2026-01-01", "to": "2026-01-31"}
    if tool_id == "web.search" and not payload:
        payload = {"query": "NexusAI smoke"}
    result = await invoke_builtin_handler(tool_id, payload, _tenant())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Builtin tools smoke")
    parser.add_argument("--list", action="store_true", help="List registered builtin tools")
    parser.add_argument("--tool", default="calendar.query", help="Tool id for dry-run")
    parser.add_argument("--payload", default=None, help="JSON payload for dry-run")
    args = parser.parse_args()
    if args.list:
        list_tools()
        return
    asyncio.run(dry_run(args.tool, args.payload))


if __name__ == "__main__":
    main()
