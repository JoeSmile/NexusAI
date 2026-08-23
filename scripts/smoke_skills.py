#!/usr/bin/env python3
"""Smoke builtin skills + skill_assets bootstrap (Task 66 slice 2)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.skill_assets.bootstrap import (
    bootstrap_builtin_skill_assets,
    validate_builtin_catalog,
)
from backend.core.skill_assets.builtin_catalog import BUILTIN_SKILL_ASSET_CATALOG
from backend.skills.registry import SkillRegistry


def list_skills() -> None:
    reg = SkillRegistry()
    reg.discover()
    ids = sorted(reg._skills.keys())  # noqa: SLF001 — smoke script
    print(f"discovered skills: {len(ids)}")
    for sid in ids:
        sk = reg.get_skill(sid)
        assert sk is not None
        print(f"  - {sid}: {sk.name} intents={sk.trigger_intents}")


def list_catalog() -> None:
    print(f"skill_asset catalog: {len(BUILTIN_SKILL_ASSET_CATALOG)}")
    for entry in BUILTIN_SKILL_ASSET_CATALOG:
        steps = (entry["ir_skeleton"].get("steps") or [])
        print(f"  - {entry['skill_id']}: {len(steps)} steps visibility={entry['visibility']}")


async def run_skill(skill_id: str) -> None:
    reg = SkillRegistry()
    reg.discover()
    skill = reg.get_skill(skill_id)
    if skill is None:
        raise SystemExit(f"skill not found: {skill_id}")
    result = await skill.execute(
        entities={"topic": "smoke test", "theme": "NexusAI", "window": "7d"},
        tenant_id=os.getenv("SMOKE_TENANT", "default"),
        user_context={
            "user_id": os.getenv("SMOKE_USER", "smoke"),
            "permissions": ["chat:write", "analytics:read", "admin:read", "rag:read"],
        },
    )
    print(f"success={result.success} error={result.error}")
    print(result.output[:500])


def bootstrap(tenant: str, user: str) -> None:
    mapping = bootstrap_builtin_skill_assets(
        tenant_id=tenant,
        owner_user_id=user,
        publish_now=True,
    )
    for sid, aid in sorted(mapping.items()):
        print(f"  {sid} -> {aid}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Builtin skills smoke")
    parser.add_argument("--list", action="store_true", help="List discovered BaseSkill classes")
    parser.add_argument("--catalog", action="store_true", help="List skill_asset catalog")
    parser.add_argument("--validate-catalog", action="store_true", help="Run publish gates on catalog")
    parser.add_argument("--run", metavar="SKILL_ID", help="Execute one builtin skill")
    parser.add_argument("--bootstrap", action="store_true", help="Seed + publish skill_assets (needs DB)")
    parser.add_argument("--tenant", default=os.getenv("SMOKE_TENANT", "default"))
    parser.add_argument("--user", default=os.getenv("SMOKE_USER", "admin"))
    args = parser.parse_args()

    if args.list:
        list_skills()
        return
    if args.catalog:
        list_catalog()
        return
    if args.validate_catalog:
        ids = validate_builtin_catalog()
        print(f"catalog gates ok: {len(ids)}")
        return
    if args.run:
        asyncio.run(run_skill(args.run))
        return
    if args.bootstrap:
        bootstrap(args.tenant, args.user)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
