"""S4 — script.gen 模板加载 + 落库走共享 generate_script。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.auth.models import TenantContext
from packages.capability.models import CapabilityKind, CapabilityProvider, CapabilitySpec
from packages.database.pgvector_session import ContentArtifact


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    ContentArtifact.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def test_persist_script_idempotent_same_body(session: Session) -> None:
    from packages.content_ops.script_persist import persist_script_artifact

    body = {"script": "家人们今天讲习惯养成"}
    id1 = persist_script_artifact(
        session,
        tenant_id="t1",
        owner_user_id="u1",
        creator_id="default",
        title="习惯养成",
        body=body,
    )
    id2 = persist_script_artifact(
        session,
        tenant_id="t1",
        owner_user_id="u1",
        creator_id="default",
        title="习惯养成",
        body=body,
    )
    assert id1 == id2
    rows = session.query(ContentArtifact).filter_by(kind="script").all()
    assert len(rows) == 1
    assert rows[0].visibility == "private"


@pytest.mark.asyncio
async def test_generate_script_auto_loads_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_load(tenant_id: str, **_kwargs):  # type: ignore[no-untyped-def]
        captured["tid"] = tenant_id
        return [
            {
                "template_type": "hook",
                "sample_count": 3,
                "structure_json": {
                    "skeleton": {
                        "template_type": "hook",
                        "hook_slots": ["痛点"],
                        "outline_slots": ["方法"],
                    }
                },
            }
        ]

    class _Harness:
        async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["prompt"] = kwargs["messages"][0]["content"]
            yield "钩子正文"

    monkeypatch.setattr(
        "packages.content_ops.script_gen.load_top_templates", fake_load
    )
    monkeypatch.setattr("packages.harness.LLMHarness", _Harness)

    from packages.content_ops.script_gen import generate_script
    from packages.content_ops.style import DEFAULT_CONTENT_STYLE

    out = await generate_script(
        tenant_id="t-edu",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={},
        hotspots=[{"title": "开学季", "summary": ""}],
        model="mock-local",
    )
    assert captured.get("tid") == "t-edu"
    assert "对标爆款结构" in captured["prompt"]
    assert "痛点" in captured["prompt"]
    assert "钩子" in out["script"]


@pytest.mark.asyncio
async def test_generate_script_persists_when_save(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict = {}

    def fake_persist(_session, **kwargs):  # type: ignore[no-untyped-def]
        called.update(kwargs)
        return "art-99"

    class _Sess:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def commit(self) -> None:
            called["committed"] = True

    class _PG:
        def Session(self):
            return _Sess()

    class _Harness:
        async def stream(self, **_kwargs):  # type: ignore[no-untyped-def]
            yield "口播正文"

    monkeypatch.setattr(
        "packages.content_ops.script_persist.persist_script_artifact", fake_persist
    )
    monkeypatch.setattr(
        "packages.database.pgvector_session.get_pg_session", lambda: _PG()
    )
    monkeypatch.setattr("packages.harness.LLMHarness", _Harness)
    monkeypatch.setattr(
        "packages.content_ops.script_gen.load_top_templates", lambda *_a, **_k: []
    )

    from packages.content_ops.script_gen import generate_script
    from packages.content_ops.style import DEFAULT_CONTENT_STYLE

    out = await generate_script(
        tenant_id="t-edu",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={},
        hotspots=[{"title": "开学季", "summary": ""}],
        model="mock-local",
        save=True,
        owner_user_id="u1",
        creator_id="default",
    )
    assert out.get("artifact_id") == "art-99"
    assert called.get("tenant_id") == "t-edu"
    assert called.get("owner_user_id") == "u1"
    assert called.get("committed") is True


@pytest.mark.asyncio
async def test_invoke_script_gen_forwards_brief_and_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def fake_gen(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {
            "script": "带模板的稿",
            "student_pii_redacted": False,
            "artifact_id": "art-1",
        }

    class _Sess:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def one_or_none(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _PG:
        def Session(self):
            return _Sess()

    monkeypatch.setattr("packages.content_ops.invoke_exec.generate_script", fake_gen)
    monkeypatch.setattr("packages.content_ops.invoke_exec.get_pg_session", lambda: _PG())

    from packages.content_ops.invoke_exec import invoke_content_ops

    spec = CapabilitySpec(
        id="script.gen",
        name="口播",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={"op": "script.gen"},
    )
    tenant = TenantContext("t-edu", "u1", "user", ["chat:write"], False)
    frames = []
    async for frame in invoke_content_ops(
        spec,
        {
            "hotspots": [{"title": "开学季", "summary": "适应"}],
            "brief": {"title": "开学", "key_points": ["作息"]},
        },
        tenant,
    ):
        frames.append(frame)

    assert captured.get("brief") == {"title": "开学", "key_points": ["作息"]}
    assert captured.get("save") is True
    assert captured.get("owner_user_id") == "u1"
    assert captured.get("templates") is None
    done = next(f for f in frames if f.get("event") == "done")
    assert done["data"]["result"]["artifact_id"] == "art-1"
    assert "带模板的稿" in str(next(f["data"] for f in frames if f.get("event") == "token"))


@pytest.mark.asyncio
async def test_generate_script_skips_persist_when_llm_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    def fake_persist(*_a, **_k):  # type: ignore[no-untyped-def]
        called["n"] += 1
        return "nope"

    class _Harness:
        async def stream(self, **_kwargs):  # type: ignore[no-untyped-def]
            from packages.fallback import get_fallback

            yield get_fallback("zh")

    monkeypatch.setattr(
        "packages.content_ops.script_persist.persist_script_artifact", fake_persist
    )
    monkeypatch.setattr("packages.harness.LLMHarness", _Harness)
    monkeypatch.setattr(
        "packages.content_ops.script_gen.load_top_templates", lambda *_a, **_k: []
    )
    monkeypatch.setenv("LLM_API_KEY", "sk-test-script")

    from packages.content_ops.script_gen import generate_script
    from packages.content_ops.style import DEFAULT_CONTENT_STYLE

    out = await generate_script(
        tenant_id="t-edu",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={},
        hotspots=[{"title": "开学季", "summary": ""}],
        model="qwen2.5:7b",
        save=True,
        owner_user_id="u1",
        creator_id="default",
    )
    assert out.get("llm_failed") is True
    assert called["n"] == 0
    assert out.get("artifact_id") is None

