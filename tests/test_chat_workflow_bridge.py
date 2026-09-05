"""Task 40.86 / 45b — chat→workflow bridge matching + bypass."""

from __future__ import annotations

from packages.pipeline.chat_workflow_bridge import (
    _plan_tags,
    bridge_run_inputs,
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


def test_bridge_run_inputs_hotspot_keeps_legacy_fields() -> None:
    payload = bridge_run_inputs(
        ir_json={"ir_schema": "1", "nodes": [], "edges": []},
        message="帮我抓下热点",
        extras={
            "intent": "hotspot",
            "conversation_id": "s1",
            "platform": "chat",
            "adapter": "topic_agent",
            "save": True,
        },
    )
    assert payload["topic"] == "帮我抓下热点"
    assert payload["adapter"] == "topic_agent"
    assert payload["save"] is True


def test_bridge_run_inputs_with_schema_uses_topic_only() -> None:
    payload = bridge_run_inputs(
        ir_json={
            "ir_schema": "1",
            "inputs": {"topic": {"name": "topic", "type": "string", "required": True}},
            "nodes": [],
            "edges": [],
        },
        message="中外合作办学口播稿",
        extras={"adapter": "topic_agent", "save": True, "platform": "chat"},
    )
    assert payload == {"topic": "中外合作办学口播稿"}


class _Asset:
    def __init__(self, asset_id: str, workflow_id: str | None = None) -> None:
        self.id = asset_id
        self.usage_stats = {"workflow_id": workflow_id} if workflow_id else {}


def test_skill_search_skips_template_without_workflow(monkeypatch) -> None:
    from packages.pipeline.chat_workflow_bridge import match_workflow_via_skill_search

    monkeypatch.setattr(
        "packages.skill_assets.service.search_published",
        lambda **k: [(_Asset("a-template"), 0.99)],
    )
    wf, asset_id = match_workflow_via_skill_search(
        tenant_id="t1", message="帮我写个口播稿", user_id="u1"
    )
    assert wf is None
    assert asset_id is None


def test_skill_search_returns_linked_published_workflow(monkeypatch) -> None:
    from packages.pipeline.chat_workflow_bridge import match_workflow_via_skill_search

    class _Wf:
        id = "wf-script"
        tenant_id = "t1"
        status = "published"
        name = "口播稿"
        ir_json = {"inputs": {"topic": {"name": "topic", "type": "string"}}}

    class _Q:
        def filter(self, *a, **k):
            return self

        def one_or_none(self):
            return _Wf()

    class _S:
        def query(self, *a, **k):
            return _Q()

        def expunge(self, obj) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _SF:
        def Session(self):
            return _S()

    monkeypatch.setattr(
        "packages.skill_assets.service.search_published",
        lambda **k: [(_Asset("a-script", "wf-script"), 0.91)],
    )
    monkeypatch.setattr(
        "packages.pipeline.chat_workflow_bridge.get_pg_session",
        lambda: _SF(),
    )
    wf, asset_id = match_workflow_via_skill_search(
        tenant_id="t1", message="帮我写个中外合作办学口播稿", user_id="u1"
    )
    assert wf is not None
    assert wf.id == "wf-script"
    assert asset_id == "a-script"


def test_skill_search_empty_hits_is_none(monkeypatch) -> None:
    from packages.pipeline.chat_workflow_bridge import match_workflow_via_skill_search

    monkeypatch.setattr(
        "packages.skill_assets.service.search_published",
        lambda **k: [],
    )
    wf, asset_id = match_workflow_via_skill_search(
        tenant_id="t1", message="你好", user_id="u1"
    )
    assert wf is None
    assert asset_id is None


def test_skill_search_skips_unpublished_workflow(monkeypatch) -> None:
    from packages.pipeline.chat_workflow_bridge import match_workflow_via_skill_search

    class _Q:
        def filter(self, *a, **k):
            return self

        def one_or_none(self):
            return None

    class _S:
        def query(self, *a, **k):
            return _Q()

        def expunge(self, obj) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _SF:
        def Session(self):
            return _S()

    monkeypatch.setattr(
        "packages.skill_assets.service.search_published",
        lambda **k: [(_Asset("a-script", "wf-archived"), 0.95)],
    )
    monkeypatch.setattr(
        "packages.pipeline.chat_workflow_bridge.get_pg_session",
        lambda: _SF(),
    )
    wf, asset_id = match_workflow_via_skill_search(
        tenant_id="t1", message="帮我写个口播稿", user_id="u1"
    )
    assert wf is None
    assert asset_id is None


def test_bridge_response_for_non_hotspot() -> None:
    from packages.pipeline.chat_workflow_bridge import bridge_triggered_copy

    text = bridge_triggered_copy(
        workflow_name="口播稿",
        run_id="r1",
        message="帮我写个口播稿",
    )
    assert "热点" not in text
    assert "口播稿" in text
    assert "r1" in text


def test_bridge_response_hotspot_keeps_content_ops_copy() -> None:
    from packages.pipeline.chat_workflow_bridge import bridge_triggered_copy

    text = bridge_triggered_copy(
        workflow_name="内置·抓取相关热点",
        run_id="r2",
        message="帮我抓下热点",
    )
    assert "热点" in text
    assert "r2" in text
