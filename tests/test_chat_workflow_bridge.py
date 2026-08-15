"""Task 40.86 — chat→workflow bridge matching."""

from __future__ import annotations

from backend.pipeline.chat_workflow_bridge import _plan_tags
from backend.pipeline.exact_cache import exact_cache_key, invalidate_exact_cache


def test_plan_tags_from_intent_and_steps() -> None:
    tags = _plan_tags(
        {
            "goal": "写口播",
            "steps": [{"capability_id": "rag-ask", "name": "检索"}],
        },
        "content_gen",
    )
    assert "content_gen" in tags
    assert "rag-ask" in tags
    assert "写口播" in tags


def test_exact_key_and_invalidate_empty() -> None:
    assert exact_cache_key("t1", "u1", "qh") == "exact:t1:u1:qh"
    assert invalidate_exact_cache("t1", "u1", "") is False
