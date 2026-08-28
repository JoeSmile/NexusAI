#!/usr/bin/env python3
"""MCP smoke — full chain: register → discover → invoke → governance audit (Task 66 s4)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mock_env() -> None:
    os.environ.setdefault("CAPABILITY_UPSTREAM_MOCK", "true")
    os.environ.setdefault(
        "MCP_SERVERS_JSON",
        json.dumps(
            [
                {
                    "id": "mock",
                    "transport": "http",
                    "url": "https://example.com/mcp",
                }
            ]
        ),
    )


def _live_env() -> None:
    os.environ.pop("CAPABILITY_UPSTREAM_MOCK", None)
    os.environ.pop("LLM_PROVIDER", None)
    os.environ["MCP_SERVERS_JSON"] = json.dumps(
        [
            {
                "id": "time",
                "transport": "stdio",
                "command": "uvx",
                "args": ["mcp-server-time"],
            }
        ]
    )


async def _run_smoke(*, with_governance: bool = True) -> dict[str, Any]:
    from packages.auth.models import TenantContext
    from backend.core.capability.connectors.mcp_server import list_server_tools
    from backend.core.capability.invoke import invoke
    from backend.core.capability.mcp_registry import (
        capability_id_for_mcp_tool,
        get_mcp_server_config,
        refresh_mcp_servers_from_env,
    )
    from backend.core.capability.registry import CapabilityRegistry
    from backend.core.tool_search import get_tool_search_index

    report: dict[str, Any] = {
        "mode": "live" if os.getenv("CAPABILITY_UPSTREAM_MOCK", "").lower() not in ("1", "true", "yes") else "mock",
        "steps": {},
    }

    reg = CapabilityRegistry()
    summary = await refresh_mcp_servers_from_env(reg)
    report["steps"]["register"] = summary
    print("1) register:", json.dumps(summary, ensure_ascii=False))

    if not summary.get("servers"):
        report["ok"] = False
        return report

    server_id = str(summary["servers"][0]["id"])
    server = get_mcp_server_config(server_id)
    tools = await list_server_tools(server)
    report["steps"]["discover"] = {"server_id": server_id, "tool_count": len(tools)}
    print(f"2) discover: server={server_id} tools={len(tools)}")
    if not tools:
        report["ok"] = False
        return report

    tool_name = "echo"
    cap_id = capability_id_for_mcp_tool(server_id, tool_name)
    if not reg.get(cap_id, require_enabled=False):
        tool_name = str(tools[0]["name"])
        cap_id = capability_id_for_mcp_tool(server_id, tool_name)
    spec = reg.get(cap_id)
    hits = get_tool_search_index().search(tool_name, top_k=5)
    report["steps"]["tool_search"] = {
        "query": tool_name,
        "hit_ids": [h.get("id") for h in hits],
        "indexed": cap_id in {h.get("id") for h in hits},
    }
    print(f"3) tool_search: indexed={report['steps']['tool_search']['indexed']}")

    tenant = TenantContext("default", "smoke", "user", ["chat:write"], False)
    payload = {"message": "smoke-mcp"} if tool_name == "echo" else {"arguments": {}}

    if with_governance:
        audits: list[dict[str, Any]] = []

        def _capture_audit(**kwargs: Any) -> bool:
            audits.append(dict(kwargs))
            return True

        with (
            patch("backend.core.capability.invoke.get_capability_registry", return_value=reg),
            patch("backend.core.capability.governance._redis", return_value=None),
            patch(
                "backend.core.audit.write_governance_audit",
                side_effect=_capture_audit,
            ),
        ):
            frames = []
            async for frame in invoke(cap_id, payload, tenant):
                frames.append(frame)
        report["steps"]["invoke"] = {
            "capability_id": cap_id,
            "events": [f.get("event") for f in frames],
            "governance_audit_calls": len(audits),
            "audit_capability_id": audits[0].get("capability_id") if audits else None,
        }
        print(
            f"4) invoke+governance: events={report['steps']['invoke']['events']} "
            f"audits={len(audits)}"
        )
        report["ok"] = any(f.get("event") == "done" for f in frames) and len(audits) >= 1
    else:
        from backend.core.capability.connectors.mcp_server import invoke_mcp

        frames = []
        async for frame in invoke_mcp(spec, payload, tenant):
            frames.append(frame)
        report["steps"]["invoke"] = {
            "capability_id": cap_id,
            "events": [f.get("event") for f in frames],
        }
        report["ok"] = any(f.get("event") == "done" for f in frames)
        print(f"4) invoke: events={report['steps']['invoke']['events']}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP full-chain smoke test")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real uvx mcp-server-time (requires network; not mock)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Skip governance chain; connector-only invoke",
    )
    args = parser.parse_args()
    if args.live:
        _live_env()
        print("L3 live mode: uvx mcp-server-time")
    else:
        _mock_env()
        print("L2 mock mode: CAPABILITY_UPSTREAM_MOCK=true")

    report = asyncio.run(_run_smoke(with_governance=not args.raw))
    print("report:", json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
