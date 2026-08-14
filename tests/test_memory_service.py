"""Task 42 S3 — dual-domain assemble."""

from __future__ import annotations

import asyncio
import json

from backend.core.guardrails.output_guard import check_role_drift
from backend.core.memory_service import MEMORY_ISOLATION_HEADER, MemoryBundle, UnifiedMemoryService


def test_assemble_skips_pending_and_filters_world_by_query():
    svc = UnifiedMemoryService(tenant_id="t")
    warm = {
        "pending:s:他": json.dumps({"antecedent": "他"}),
        "fact:星火": "项目代号星火",
        "entity:王工": json.dumps(
            {"name": "王工", "relation": "同事", "text": "王工", "type": "entity"}
        ),
        "todo:报表": json.dumps(
            {
                "action": "提交预算报表",
                "owner_kind": "self",
                "status": "open",
                "text": "提交预算报表",
            }
        ),
        "decision:redis": json.dumps(
            {"statement": "缓存方案改用 Redis 集群", "text": "Redis"}
        ),
    }
    block = svc.assemble_prompt_block(
        MemoryBundle(warm=warm, hot=[], cold=[]),
        query="王工报表",
    )
    assert MEMORY_ISOLATION_HEADER in block
    assert "pending" not in block
    assert "王工" in block
    assert "提交预算报表" in block
    assert "用户背景" in block or "星火" in block


def test_assemble_world_miss_without_query_hit():
    svc = UnifiedMemoryService(tenant_id="t")
    warm = {
        "entity:李四": json.dumps({"name": "李四", "relation": "客户", "text": "李四"}),
    }
    block = svc.assemble_prompt_block(
        MemoryBundle(warm=warm),
        query="今天天气",
    )
    assert "李四" not in block


def test_half_structured_no_role_drift():
    text = (
        f"{MEMORY_ISOLATION_HEADER}\n\n"
        "[活跃待办]\n- 周五前提交预算报表 (owner:自己)\n\n"
        "[近期决策]\n- 缓存方案改用 Redis 集群\n\n"
        "[用户提到的对象]\n- 王工(同事)"
    )

    async def _run():
        return await check_role_drift(text)

    drift = asyncio.run(_run())
    assert drift.action == "pass"
