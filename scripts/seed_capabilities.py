#!/usr/bin/env python3
"""Seed 演示 Capability / Agent（Task 30.24）— 写入 capabilities 表，非 env 硬编码。"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from packages.database.pgvector_session import get_pg_session


def _tool_contract(
    cap_id: str,
    *,
    description: str,
    input_schema: dict,
    output_schema: dict,
    examples: list[dict],
    idempotency_key_args: list[str] | None = None,
    retryable: bool = True,
    idempotent: bool = False,
) -> dict:
    """Task 56 ToolContract 片段（写入 spec.tool_contract）。"""
    return {
        "name": cap_id,
        "version": "v1",
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "failure_semantics": {
            "retryable": retryable,
            "idempotent": idempotent,
            "requires_compensation": False,
            "failure_codes": ["CAP_003", "CAP_005"],
        },
        "idempotency_key_args": list(idempotency_key_args or []),
        "examples": examples,
    }


# 叶子 + 嵌套 Agent（vendor-risk → contract-query → rag-ask）
# leaf=true：仅 LEAF_STUB_MODE=true 时降级 stub；默认经 executor 走真实 invoke（Task 30b）
SEED_CAPS: list[dict] = [
    {
        "id": "rag-ask",
        "name": "RAG Ask",
        "kind": "tool",
        "provider": "nexusai",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "leaf": True,
            "executor": "rag",
        },
        "param_spec": {
            "query": {
                "type": "string",
                "required": True,
                "description": "检索问题",
            },
            "search_k": {
                "type": "number",
                "required": False,
                "default": 3,
                "description": "检索条数",
            },
        },
        "cost_model": {"cost_per_1k": 0.01},
    },
    {
        "id": "nexusai-chat",
        "name": "NexusAI Chat",
        "kind": "tool",
        "provider": "nexusai",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "leaf": True,
            "chain_audit": False,
            "executor": "model",
        },
        "param_spec": {
            "message": {
                "type": "string",
                "required": True,
                "description": "用户消息",
            },
        },
        "cost_model": {"cost_per_1k": 0.01},
    },
    {
        "id": "contract-query-agent",
        "name": "Contract Query Agent",
        "kind": "agent",
        "provider": "nexusai",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "role": "contract_analyst",
            "system_prompt_ref": "agents/contract-query",
            "capabilities": ["rag-ask", "nexusai-chat"],
            "memory": True,
        },
        "cost_model": {"cost_per_1k": 0.05},
    },
    {
        "id": "vendor-risk-agent",
        "name": "Vendor Risk Agent",
        "kind": "agent",
        "provider": "nexusai",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "role": "risk_officer",
            "system_prompt_ref": "agents/vendor-risk",
            "capabilities": ["contract-query-agent", "nexusai-chat"],
            "memory": True,
        },
        "cost_model": {"cost_per_1k": 0.08},
    },
    {
        "id": "hotspot.dig",
        "name": "相关热点挖掘",
        "kind": "tool",
        "provider": "nexusai",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "leaf": True,
            "executor": "content_ops",
            "op": "hotspot.dig",
            "tool_contract": _tool_contract(
                "hotspot.dig",
                description="挖掘相关热点列表，供口播与选题使用",
                input_schema={
                    "type": "object",
                    "properties": {
                        "adapter": {"type": "string"},
                        "categories": {"type": "array"},
                        "keywords": {"type": "string"},
                        "paste_text": {"type": "string"},
                    },
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "items": {"type": "array"},
                        "adapter": {"type": "string"},
                    },
                    "required": ["items"],
                },
                examples=[
                    {
                        "input": {"adapter": "topic_agent", "keywords": "AI"},
                        "output": {"items": [{"title": "示例热点"}], "adapter": "topic_agent"},
                    }
                ],
                idempotency_key_args=["adapter", "keywords"],
                idempotent=True,
            ),
        },
        "param_spec": {
            "adapter": {
                "type": "string",
                "required": False,
                "default": "topic_agent",
                "description": "topic_agent | paste | seed",
            },
            "categories": {"type": "array", "required": False},
            "keywords": {"type": "string", "required": False},
            "paste_text": {"type": "string", "required": False},
        },
        "cost_model": {"cost_per_1k": 0.01},
    },
    {
        "id": "script.gen",
        "name": "风格化口播生成",
        "kind": "tool",
        "provider": "nexusai",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "leaf": True,
            "executor": "content_ops",
            "op": "script.gen",
            "tool_contract": _tool_contract(
                "script.gen",
                description="按主讲风格生成口播稿，可引用热点输入",
                input_schema={
                    "type": "object",
                    "properties": {
                        "creator_id": {"type": "string"},
                        "hotspots": {"type": "array"},
                        "duration_sec": {"type": "number"},
                        "platform": {"type": "string"},
                    },
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "script": {"type": "string"},
                        "creator_id": {"type": "string"},
                    },
                    "required": ["script"],
                },
                examples=[
                    {
                        "input": {"creator_id": "default", "duration_sec": 60},
                        "output": {"script": "大家好……", "creator_id": "default"},
                    }
                ],
                idempotency_key_args=["creator_id", "duration_sec"],
            ),
        },
        "param_spec": {
            "creator_id": {"type": "string", "required": False, "default": "default"},
            "hotspots": {"type": "array", "required": False},
            "duration_sec": {"type": "number", "required": False, "default": 60},
            "platform": {"type": "string", "required": False},
        },
        "cost_model": {"cost_per_1k": 0.02},
    },
    {
        "id": "style.extract",
        "name": "主讲风格提取",
        "kind": "tool",
        "provider": "nexusai",
        "permission": "chat:write",
        "tenant_id": "*",
        "spec": {
            "governance": True,
            "leaf": True,
            "executor": "content_ops",
            "op": "style.extract",
            "tool_contract": _tool_contract(
                "style.extract",
                description="从口播逐字稿提取主讲风格画像并可选落库",
                input_schema={
                    "type": "object",
                    "properties": {
                        "creator_id": {"type": "string"},
                        "text": {"type": "string"},
                        "save": {"type": "boolean"},
                    },
                    "required": ["text"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "style": {"type": "object"},
                        "creator_id": {"type": "string"},
                    },
                    "required": ["style"],
                },
                examples=[
                    {
                        "input": {"text": "大家好我是……", "creator_id": "default"},
                        "output": {"style": {"tone": "亲和"}, "creator_id": "default"},
                    }
                ],
                idempotency_key_args=["creator_id"],
                idempotent=True,
            ),
        },
        "param_spec": {
            "creator_id": {"type": "string", "required": False, "default": "default"},
            "text": {"type": "string", "required": True, "description": "演讲/口播逐字稿"},
            "save": {"type": "boolean", "required": False, "default": True},
        },
        "cost_model": {"cost_per_1k": 0.01},
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
        ps = row.get("param_spec")
        params = {
            "id": row["id"],
            "tid": row["tenant_id"],
            "name": row["name"],
            "kind": row["kind"],
            "provider": row["provider"],
            "spec": json.dumps(row["spec"], ensure_ascii=False),
            "status": "enabled",
            "cost": json.dumps(row.get("cost_model") or {}),
            "perm": row.get("permission"),
            "param_spec": json.dumps(ps, ensure_ascii=False) if ps is not None else None,
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
                        param_spec=CAST(:param_spec AS jsonb),
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
                     cost_model, permission, param_spec, created_at, updated_at)
                VALUES
                    (:id, :tid, :name, :kind, :provider, CAST(:spec AS json), :status,
                     CAST(:cost AS json), :perm, CAST(:param_spec AS jsonb), :now, :now)
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
        from packages.capability.registry import reload_capability_registry

        reg = reload_capability_registry()
        agents = [s.id for s in reg.list(kind="agent")]
        print("-" * 70)
        print(f"  registry agents: {agents}")
    except Exception as exc:
        print(f"  (registry reload skipped: {exc})")
    print("=" * 70)


if __name__ == "__main__":
    main()
