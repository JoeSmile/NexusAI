"""Task 41 S2a — select_world_items + 换措辞语义命中。"""

from __future__ import annotations

import json
from unittest.mock import patch

from backend.core.memory.select_world_items import (
    keyword_select,
    select_world_items,
)
from backend.core.memory_service import MEMORY_ISOLATION_HEADER, MemoryBundle, UnifiedMemoryService


def _decision_warm() -> dict[str, str]:
    return {
        "decision:分布式锁防": json.dumps(
            {
                "statement": "采用分布式锁防止超卖",
                "text": "采用分布式锁防止超卖",
            }
        ),
        "entity:王工": json.dumps(
            {"name": "王工", "relation": "同事", "text": "王工", "type": "person"}
        ),
        "fact:星火": "项目代号星火",
    }


def test_keyword_select_hits_shared_bigram() -> None:
    items = _decision_warm()
    keys = keyword_select("王工在吗", items)
    assert "entity:王工" in keys
    assert "decision:分布式锁防" not in keys


def test_keyword_miss_on_paraphrase() -> None:
    """换措辞无共同 2-gram → 关键词 miss（AC 前提）。"""
    items = _decision_warm()
    keys = keyword_select("库存怎么避免被抢光", items)
    assert "decision:分布式锁防" not in keys


def test_semantic_paraphrase_hits_when_search_returns_key() -> None:
    items = _decision_warm()
    with (
        patch(
            "backend.database.embeddings.embedding_uses_hash_fallback",
            return_value=False,
        ),
        patch(
            "backend.database.vector_ops.search_user_memories",
            return_value=[
                {
                    "key": "decision:分布式锁防",
                    "similarity": 0.88,
                    "value": items["decision:分布式锁防"],
                }
            ],
        ),
    ):
        keys = select_world_items(
            "库存怎么避免被抢光",
            items,
            mode="semantic",
            tenant_id="t1",
            user_id="u1",
        )
    assert keys == ["decision:分布式锁防"]


def test_semantic_hash_fallback_uses_keyword() -> None:
    items = _decision_warm()
    with patch(
        "backend.database.embeddings.embedding_uses_hash_fallback",
        return_value=True,
    ):
        keys = select_world_items(
            "库存怎么避免被抢光",
            items,
            mode="semantic",
            tenant_id="t1",
            user_id="u1",
        )
    assert keys == keyword_select("库存怎么避免被抢光", items)


def test_assemble_render_identical_for_same_selection() -> None:
    """P0-2：关键词与语义路径渲染格式一致，仅选择集不同。"""
    svc = UnifiedMemoryService(tenant_id="t")
    warm = _decision_warm()
    warm["todo:报表"] = json.dumps(
        {
            "action": "提交预算报表",
            "owner_kind": "self",
            "status": "open",
            "text": "提交预算报表",
        }
    )
    bundle = MemoryBundle(warm=warm, hot=[], cold=[])

    with patch(
        "backend.core.memory.select_world_items.select_world_items",
        return_value=["decision:分布式锁防"],
    ):
        block_a = svc.assemble_prompt_block(
            bundle, query="任意", user_id="u1", retrieval_mode="semantic"
        )
    with patch(
        "backend.core.memory.select_world_items.select_world_items",
        return_value=["decision:分布式锁防"],
    ):
        block_b = svc.assemble_prompt_block(
            bundle, query="任意", user_id="u1", retrieval_mode="keyword"
        )
    assert block_a == block_b
    assert MEMORY_ISOLATION_HEADER in block_a
    assert "采用分布式锁防止超卖" in block_a
    assert "提交预算报表" in block_a
    assert "王工" not in block_a


def test_assemble_paraphrase_via_semantic_mock() -> None:
    svc = UnifiedMemoryService(tenant_id="t")
    warm = _decision_warm()
    with (
        patch(
            "backend.database.embeddings.embedding_uses_hash_fallback",
            return_value=False,
        ),
        patch(
            "backend.database.vector_ops.search_user_memories",
            return_value=[
                {
                    "key": "decision:分布式锁防",
                    "similarity": 0.9,
                    "value": warm["decision:分布式锁防"],
                }
            ],
        ),
    ):
        block = svc.assemble_prompt_block(
            MemoryBundle(warm=warm),
            query="库存怎么避免被抢光",
            user_id="u1",
            retrieval_mode="semantic",
        )
    assert "采用分布式锁防止超卖" in block
