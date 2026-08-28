#!/usr/bin/env python3
"""Task 66 slice 4 — one-command tool ecosystem smoke (builtin + skills + MCP)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _run_py(args: list[str]) -> int:
    cmd = [sys.executable, *args]
    print(f"\n>>> {' '.join(args)}")
    return subprocess.call(cmd, cwd=ROOT)


def _gold_line_demo() -> None:
    """Skill catalog weekly_report PlanIR (no DB)."""
    from backend.core.skill_assets.builtin_catalog import BUILTIN_SKILL_ASSET_CATALOG

    entry = next(e for e in BUILTIN_SKILL_ASSET_CATALOG if e["skill_id"] == "weekly_report")
    steps = entry["ir_skeleton"]["steps"]
    parallel = [s["id"] for s in steps if not s.get("depends_on")]
    print("\n=== gold line (catalog) ===")
    print("query: 把上周热点做成社媒文案周报")
    print("skill: weekly_report")
    print(f"parallel steps: {parallel}")
    print("merge step: report depends_on dig+metrics")


async def _counts() -> dict[str, int]:
    from packages.capability.builtin.register import register_builtin_tools
    from packages.capability.builtin.specs import BUILTIN_TOOL_SPECS
    from backend.core.skill_assets.bootstrap import validate_builtin_catalog
    from backend.core.skill_assets.builtin_catalog import (
        BUILTIN_SKILL_ASSET_CATALOG,
        BUILTIN_SKILL_IDS,
    )
    from backend.skills.registry import SkillRegistry

    reg_skill = SkillRegistry()
    reg_skill.discover()
    validate_builtin_catalog()

    from packages.capability.registry import CapabilityRegistry

    reg = CapabilityRegistry()
    register_builtin_tools(reg)

    return {
        "builtin_tools": len(BUILTIN_TOOL_SPECS),
        "builtin_skills": len(BUILTIN_SKILL_IDS),
        "skill_assets_catalog": len(BUILTIN_SKILL_ASSET_CATALOG),
        "registry_builtin_tools": len(
            [s for s in reg.list(kind="tool") if s.provider.value == "nexusai"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool ecosystem smoke (Task 66)")
    parser.add_argument("--live-mcp", action="store_true", help="MCP L3 live uvx server")
    parser.add_argument("--skip-mcp", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("CAPABILITY_UPSTREAM_MOCK", "true")

    counts = asyncio.run(_counts())
    print("=== inventory ===", json.dumps(counts, ensure_ascii=False))

    code = _run_py(["scripts/smoke_tools.py", "--list"])
    if code != 0:
        raise SystemExit(code)

    code = _run_py(["scripts/smoke_skills.py", "--list"])
    if code != 0:
        raise SystemExit(code)
    code = _run_py(["scripts/smoke_skills.py", "--validate-catalog"])
    if code != 0:
        raise SystemExit(code)

    _gold_line_demo()

    if not args.skip_mcp:
        mcp_args = ["scripts/smoke_mcp.py"]
        if args.live_mcp:
            mcp_args.append("--live")
        code = _run_py(mcp_args)
        if code != 0:
            raise SystemExit(code)

    print("\n=== tool ecosystem smoke OK ===")
    print(
        "叙事: 内置工具是自产，MCP 是外购，都过同一条治理链，审批/配额/审计一个不漏。"
    )


if __name__ == "__main__":
    main()
