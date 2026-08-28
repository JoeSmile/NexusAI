"""Task 41 S2a — select_world_items + 换措辞语义命中。"""

from __future__ import annotations

import json
from unittest.mock import patch

from packages.memory.select_world_items import (
    keyword_select,
    select_world_items,
)
from packages.memory.memory_service import MEMORY_ISOLATION_HEADER, MemoryBundle, UnifiedMemoryService


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


def _world_keys(n: int, extra: dict[str, str] | None = None) -> dict[str, str]:
    items: dict[str, str] = dict(extra or {})
    i = 0
    while sum(1 for k in items if k.startswith(("entity:", "decision:", "error:"))) < n:
        items[f"entity:pad-{i}"] = json.dumps(
            {"name": f"p{i}", "text": f"pad-{i}", "type": "entity"}
        )
        i += 1
    return items


def test_semantic_paraphrase_hits_when_search_returns_key() -> None:
    items = _world_keys(25, _decision_warm())
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
    items = _world_keys(25, _decision_warm())
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
        "packages.memory.select_world_items.select_world_items",
        return_value=["decision:分布式锁防"],
    ):
        block_a = svc.assemble_prompt_block(
            bundle, query="任意", user_id="u1", retrieval_mode="semantic"
        )
    with patch(
        "packages.memory.select_world_items.select_world_items",
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
    warm = _world_keys(25, _decision_warm())
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
    assert "王工" not in block


def test_small_world_semantic_skips_embed(monkeypatch) -> None:
    """Task 51: ≤20 world keys → full inject, no embedding API."""
    items = _world_keys(15)
    called = {"embed": 0, "search": 0}

    def _boom_embed(*_a, **_k):
        called["embed"] += 1
        raise AssertionError("embed_text must not run for small world")

    def _boom_search(*_a, **_k):
        called["search"] += 1
        raise AssertionError("search_user_memories must not run for small world")

    monkeypatch.setattr(
        "backend.database.embeddings.embedding_uses_hash_fallback", lambda: False
    )
    monkeypatch.setattr("backend.database.embeddings.embed_text", _boom_embed)
    monkeypatch.setattr(
        "backend.database.vector_ops.search_user_memories", _boom_search
    )
    keys = select_world_items(
        "任意查询需要走语义",
        items,
        mode="semantic",
        tenant_id="t1",
        user_id="u1",
    )
    assert called["embed"] == 0
    assert called["search"] == 0
    world = {
        k
        for k in items
        if k.startswith(("entity:", "decision:", "error:"))
    }
    assert set(keys) == world
    assert len(keys) == 15


def test_large_world_semantic_still_searches(monkeypatch) -> None:
    items = _world_keys(50)
    monkeypatch.setattr(
        "backend.database.embeddings.embedding_uses_hash_fallback", lambda: False
    )
    hits = [
        {
            "key": "entity:pad-0",
            "similarity": 0.9,
            "value": items["entity:pad-0"],
        }
    ]
    with patch(
        "backend.database.vector_ops.search_user_memories",
        return_value=hits,
    ) as search:
        keys = select_world_items(
            "查询 pad-0",
            items,
            mode="semantic",
            tenant_id="t1",
            user_id="u1",
        )
    search.assert_called_once()
    assert keys == ["entity:pad-0"]


def test_small_world_threshold_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_SMALL_WORLD_THRESHOLD", "50")
    items = _world_keys(40)
    monkeypatch.setattr(
        "backend.database.embeddings.embedding_uses_hash_fallback", lambda: False
    )

    def _boom_search(*_a, **_k):
        raise AssertionError("threshold 50 should skip search for n=40")

    monkeypatch.setattr(
        "backend.database.vector_ops.search_user_memories", _boom_search
    )
    keys = select_world_items(
        "查询",
        items,
        mode="semantic",
        tenant_id="t1",
        user_id="u1",
    )
    assert len(keys) == 40
