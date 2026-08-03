"""Task 34.02 — UnifiedMemoryService write/read 骨架。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.core.memory_service import (
    MEMORY_ISOLATION_HEADER,
    MemoryBundle,
    UnifiedMemoryService,
)


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self._chat: list[SimpleNamespace] = []
        self._warm: list[SimpleNamespace] = []
        self._cold: list[SimpleNamespace] = []

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", str(model))
        q = MagicMock()
        if name == "ChatSession":
            q.filter_by.return_value.first.return_value = None
            return q
        if name == "ChatMessage":

            def _filter_by(**_k):
                return q

            q.filter_by.side_effect = _filter_by
            q.order_by.return_value.limit.return_value.all.return_value = list(
                reversed(self._chat)
            )
            return q
        if name == "UserMemory":
            q.filter_by.return_value.all.return_value = self._warm
            return q
        if name == "ColdMemory":
            q.filter_by.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = list(
                reversed(self._cold)
            )
            q.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = list(
                reversed(self._cold)
            )
            return q
        return q

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)
        name = type(obj).__name__
        if name == "ChatMessage":
            self._chat.append(
                SimpleNamespace(role=obj.role, content=obj.content, created_at=None)
            )
        if name == "ColdMemory":
            obj.id = len(self._cold) + 1
            self._cold.append(
                SimpleNamespace(
                    id=obj.id,
                    summary=obj.summary,
                    session_id=obj.session_id,
                    created_at=None,
                )
            )

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeFactory:
    def __init__(self, sess: _FakeSession) -> None:
        self.Session = lambda: sess  # noqa: E731


@pytest.mark.asyncio
async def test_write_turn_and_read_hot() -> None:
    sess = _FakeSession()
    svc = UnifiedMemoryService(tenant_id="t1")
    with patch(
        "backend.core.memory_service.get_pg_session",
        return_value=_FakeFactory(sess),
    ):
        out = await svc.write_turn(
            user_id="u1",
            session_id="s1",
            user_message="hi",
            assistant_message="hello",
        )
        assert out["wrote_user"] and out["wrote_assistant"]
        assert sess.committed
        bundle = await svc.read(user_id="u1", include_warm=False, include_cold=False)
    assert len(bundle.hot) == 2
    assert bundle.hot[0]["role"] == "user"


@pytest.mark.asyncio
async def test_write_warm_delegates_store() -> None:
    svc = UnifiedMemoryService(tenant_id="t1")
    with patch(
        "backend.core.memory_service.store_user_memory", return_value=42
    ) as store:
        out = await svc.write(
            "warm",
            user_id="u1",
            key="pref:tone",
            value="formal",
            confidence=0.9,
        )
    assert out["id"] == 42
    store.assert_called_once()


@pytest.mark.asyncio
async def test_write_cold() -> None:
    sess = _FakeSession()
    svc = UnifiedMemoryService(tenant_id="t1")
    with patch(
        "backend.core.memory_service.get_pg_session",
        return_value=_FakeFactory(sess),
    ):
        out = await svc.write_cold(user_id="u1", summary="谈了供应商风险", session_id="s1")
    assert out["tier"] == "cold"
    assert out["id"] == 1


def test_assemble_prompt_block_has_isolation_and_budget() -> None:
    bundle = MemoryBundle(
        hot=[{"role": "user", "content": "a" * 400}],
        warm={"profile:v1": "{}"},
        cold=[
            {"summary": "old-summary-" + ("x" * 200)},
            {"summary": "new-summary-" + ("y" * 200)},
        ],
    )
    svc = UnifiedMemoryService()
    text = svc.assemble_prompt_block(
        bundle, context_window_tokens=200, budget_ratio=0.3
    )
    assert MEMORY_ISOLATION_HEADER in text
    assert "画像" in text or "profile" in text.lower() or "偏好" in text
    # 小预算应丢弃部分 cold/hot，但隔离头保留
    assert text.startswith(MEMORY_ISOLATION_HEADER)


def test_rule_based_session_summary() -> None:
    from backend.core.memory_service import rule_based_session_summary

    text = rule_based_session_summary(
        [
            {"role": "user", "content": "你好，我想了解供应商风险"},
            {"role": "assistant", "content": "请提供供应商名称"},
            {"role": "user", "content": "供应商A的合同条款如何？"},
            {"role": "assistant", "content": "需要查阅合同库"},
            {"role": "user", "content": "好的，帮我查一下"},
            {"role": "assistant", "content": "已检索相关条款"},
        ]
    )
    assert "开场" in text
    assert "近况" in text
    assert "助手末回" in text


def test_list_session_messages_head_tail_skips_middle() -> None:
    """长会话只取头尾，近况来自末条而非中间。"""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from backend.core.memory_service import (
        UnifiedMemoryService,
        rule_based_session_summary,
    )

    # 60 条：头 2 + 尾 2，中间应被跳过
    rows = [
        SimpleNamespace(
            id=i,
            role="user" if i % 2 == 0 else "assistant",
            content=f"m{i}",
            created_at=i,
        )
        for i in range(60)
    ]

    class _Sess:
        def __init__(self) -> None:
            self._order_calls = 0

        def query(self, model):  # noqa: ANN001
            q = MagicMock()
            filt = MagicMock()
            q.filter_by.return_value = filt
            filt.count.return_value = 60

            def order_by(_col):  # noqa: ANN001
                chain = MagicMock()
                idx = self._order_calls
                self._order_calls += 1

                def _limit(n: int):
                    lim = MagicMock()
                    if idx == 0:
                        lim.all.return_value = rows[:n]
                    else:
                        lim.all.return_value = list(reversed(rows[-n:]))
                    return lim

                chain.limit.side_effect = _limit
                return chain

            filt.order_by.side_effect = order_by
            return q

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    svc = UnifiedMemoryService(tenant_id="t1")
    with patch(
        "backend.core.memory_service.get_pg_session",
        return_value=MagicMock(Session=lambda: _Sess()),
    ):
        out = svc.list_session_messages_head_tail(
            user_id="u1", session_id="s1", head_k=2, tail_k=2
        )
    assert [m["content"] for m in out] == ["m0", "m1", "m58", "m59"]
    summary = rule_based_session_summary(out)
    assert "开场" in summary and "m0" in summary
    assert "近况" in summary and ("m58" in summary or "m59" in summary)


@pytest.mark.asyncio
async def test_maybe_cold_summarize_triggers_on_threshold() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from backend.core.memory_service import UnifiedMemoryService

    msgs = [
        SimpleNamespace(role="user", content=f"q{i}", created_at=None)
        for i in range(5)
    ] + [
        SimpleNamespace(role="assistant", content=f"a{i}", created_at=None)
        for i in range(5)
    ]

    class _Sess:
        def query(self, model):  # noqa: ANN001
            q = MagicMock()
            name = getattr(model, "__name__", "")
            if name == "ChatMessage":
                q.filter_by.return_value.count.return_value = 10
                q.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = (
                    msgs
                )
                return q
            if name == "ColdMemory":
                return q
            return q

        def add(self, obj) -> None:  # noqa: ANN001
            obj.id = 99

        def commit(self) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    svc = UnifiedMemoryService(tenant_id="t1")
    with patch(
        "backend.core.memory_service.get_pg_session",
        return_value=MagicMock(Session=lambda: _Sess()),
    ):
        out = await svc.maybe_cold_summarize(
            user_id="u1", session_id="s1", min_messages=10
        )
        skip = await svc.maybe_cold_summarize(
            user_id="u1", session_id="s1", min_messages=12
        )
    assert out is not None
    assert out["tier"] == "cold"
    assert out["method"] == "rule"
    assert "[msgs=10]" in (out.get("summary") or "")
    assert skip is None


def test_decay_score_matches_enhanced_curve() -> None:
    from backend.core.memory_service import decay_score

    assert decay_score(1.0, 0) == 1.0
    assert abs(decay_score(1.0, 1) - 0.9) < 1e-9
    assert abs(decay_score(1.0, 2) - 0.81) < 1e-9


@pytest.mark.asyncio
async def test_forget_user_clears_warm_cold_and_redacts() -> None:
    from unittest.mock import MagicMock, patch

    from backend.core.memory_service import REDACTED_MESSAGE, UnifiedMemoryService

    class _Sess:
        def __init__(self) -> None:
            self.committed = False

        def query(self, model):  # noqa: ANN001
            q = MagicMock()
            name = getattr(model, "__name__", "")
            filt = MagicMock()
            q.filter_by.return_value = filt
            if name == "UserMemory":
                filt.delete.return_value = 2
            elif name == "ColdMemory":
                filt.delete.return_value = 1
            elif name == "ChatMessage":
                filt.filter.return_value.update.return_value = 3
            return q

        def commit(self) -> None:
            self.committed = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    sess = _Sess()
    svc = UnifiedMemoryService(tenant_id="t1")
    with patch(
        "backend.core.memory_service.get_pg_session",
        return_value=MagicMock(Session=lambda: sess),
    ):
        out = await svc.forget_user("u1")
    assert out["deleted_warm"] == 2
    assert out["deleted_cold"] == 1
    assert out["redacted_messages"] == 3
    assert sess.committed
    assert REDACTED_MESSAGE == "[REDACTED]"


@pytest.mark.asyncio
async def test_build_context_strips_memory_on_role_drift() -> None:
    from backend.core.memory_service import MEMORY_ISOLATION_HEADER
    from backend.pipeline.nodes.build_context import build_context
    from backend.pipeline.state import make_initial_state

    state = make_initial_state("t1", "u1", "s1", "你好")
    state["warm_memory"] = {"note": "家人们快来直播间"}
    state["hot_memory"] = []
    state["cold_memory"] = []
    out = await build_context(state)
    assert MEMORY_ISOLATION_HEADER in out["raw_input"]
    assert "家人们" not in out["raw_input"]
    assert "user: 你好" in out["raw_input"]


def test_prompt_composer_clamps_relaxed_style() -> None:
    from backend.core.memory_service import MEMORY_ISOLATION_HEADER
    from backend.services.prompt_composer import PromptComposer

    text = PromptComposer(
        {
            "formality": 0.1,
            "enthusiasm": 0.95,
            "humor_level": 0.9,
            "use_emoji": True,
            "preferred_topics": ["合规"],
        }
    ).compose()
    assert MEMORY_ISOLATION_HEADER in text
    assert "轻松随意" not in text
    assert "热情活泼" not in text
    assert "不使用emoji" in text
