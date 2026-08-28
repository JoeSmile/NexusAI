"""Task 40.86 / 45b — chat→workflow bridge matching + bypass."""

from __future__ import annotations

from packages.pipeline.chat_workflow_bridge import (
    _plan_tags,
    match_published_workflow,
    message_intent_tags,
    should_skip_workflow_bridge,
)
from packages.pipeline.exact_cache import exact_cache_key, invalidate_exact_cache


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


def test_bypass_markers() -> None:
    assert should_skip_workflow_bridge("你直接抓,别走流程")
    assert should_skip_workflow_bridge("不用workflow，随便说说")
    assert not should_skip_workflow_bridge("帮我抓下热点")


def test_message_intent_tags_hotspot() -> None:
    tags = message_intent_tags("帮我抓下热点吧")
    assert "hotspot" in tags
    assert "抓热点" in tags
    assert message_intent_tags("今天天气怎么样") == set()


def test_match_requires_overlap_or_none_without_db_rows(monkeypatch) -> None:
    """No published rows → None (isolation when tenant has no tagged workflows)."""

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return []

    class _S:
        def query(self, *a, **k):
            return _Q()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _SF:
        def Session(self):
            return _S()

    monkeypatch.setattr(
        "packages.pipeline.chat_workflow_bridge.get_pg_session",
        lambda: _SF(),
    )
    assert (
        match_published_workflow(
            tenant_id="t-empty",
            plan=None,
            intent=None,
            confidence=0.9,
            message="帮我抓下热点",
        )
        is None
    )
