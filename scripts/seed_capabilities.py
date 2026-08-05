#!/usr/bin/env python3
"""Seed 演示 Capability / Agent（Task 30.24）— 写入 capabilities 表，非 env 硬编码。"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session

# 叶子 + 嵌套 Agent（vendor-risk → contract-query → rag-ask）
# leaf=true：仅 LEAF_STUB_MODE=true 时降级 stub；默认经 executor 走真实 invoke（Task 30b）
SEED_CAPS: list[dict] = [
    {
        "id": "rag-ask",
        "name": "RAG Ask",
        "kind": "tool",
        "provider": "contextgate",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "leaf": True,
            "executor": "rag",
        },
        "cost_model": {"cost_per_1k": 0.01},
    },
    {
        "id": "contextgate-chat",
        "name": "NexusAI Chat",
        "kind": "tool",
        "provider": "contextgate",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "leaf": True,
            "chain_audit": False,
            "executor": "model",
        },
        "cost_model": {"cost_per_1k": 0.01},
    },
    {
        "id": "contract-query-agent",
        "name": "Contract Query Agent",
        "kind": "agent",
        "provider": "contextgate",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "role": "contract_analyst",
            "system_prompt_ref": "agents/contract-query",
            "capabilities": ["rag-ask", "contextgate-chat"],
            "memory": True,
        },
        "cost_model": {"cost_per_1k": 0.05},
    },
    {
        "id": "vendor-risk-agent",
        "name": "Vendor Risk Agent",
        "kind": "agent",
        "provider": "contextgate",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "role": "risk_officer",
            "system_prompt_ref": "agents/vendor-risk",
            "capabilities": ["contract-query-agent", "contextgate-chat"],
            "memory": True,
        },
        "cost_model": {"cost_per_1k": 0.08},
    },
]


def upsert_capability(row: dict) -> str:
    session_factory = get_pg_session()
    now = datetime.utcnow()
    with session_factory.Session() as session:
        existing = session.execute(
            text("SELECT id FROM capabilities WHERE id = :id"),
            {"id": row["id"]},
        ).fetchone()
        params = {
            "id": row["id"],
            "tid": row["tenant_id"],
            "name": row["name"],
            "kind": row["kind"],
            "provider": row["provider"],
            "spec": json.dumps(row["spec"], ensure_ascii=False),
            "status": "enabled",
            "cost": json.dumps(row.get("cost_model") or {}),
            "perm": row.get("permission") or "chat:write",
            "now": now,
        }
        if existing:
            session.execute(
                text(
                    """
                    UPDATE capabilities SET
                        tenant_id=:tid, name=:name, kind=:kind, provider=:provider,
                        spec=CAST(:spec AS json), status=:status,
                        cost_model=CAST(:cost AS json), permission=:perm,
                        updated_at=:now
                    WHERE id=:id
                    """
                ),
                params,
            )
            session.commit()
            return "UPDATED"
        session.execute(
            text(
                """
                INSERT INTO capabilities
                    (id, tenant_id, name, kind, provider, spec, status,
                     cost_model, permission, created_at, updated_at)
                VALUES
                    (:id, :tid, :name, :kind, :provider, CAST(:spec AS json), :status,
                     CAST(:cost AS json), :perm, :now, :now)
                """
            ),
            params,
        )
        session.commit()
        return "CREATED"


def main() -> None:
    print("=" * 70)
    print("  NexusAI — Seed Capabilities / Agents (30.24)")
    print("=" * 70)
    for row in SEED_CAPS:
        status = upsert_capability(row)
        print(f"  [{status:7s}] {row['kind']:12s} {row['id']}")
    try:
        from backend.core.capability.registry import reload_capability_registry

        reg = reload_capability_registry()
        agents = [s.id for s in reg.list(kind="agent")]
        print("-" * 70)
        print(f"  registry agents: {agents}")
    except Exception as exc:
        print(f"  (registry reload skipped: {exc})")
    print("=" * 70)


if __name__ == "__main__":
    main()
