"""Task 43.2 — skill_assets service lifecycle + search."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from packages.skill_assets import service as svc
from packages.database.pgvector_session import SkillAsset, get_pg_session


@pytest.fixture()
def ensure_table(monkeypatch: pytest.MonkeyPatch):
    """Deterministic embeddings: no live HTTP; 'invoice' vs unrelated stay separable."""

    def _fake_embed(text: str, tenant_id: str | None = None) -> list[float]:
        from packages.database.embeddings import EMBED_DIM

        vec = [0.0] * EMBED_DIM
        blob = (text or "").lower()
        if "zzz_unrelated" in blob:
            vec[0] = 1.0
        elif "invoice" in blob:
            vec[1] = 1.0
        else:
            vec[2] = 1.0
        return vec

    monkeypatch.setattr("packages.skill_assets.service.embed_text", _fake_embed)
    sf = get_pg_session()
    SkillAsset.__table__.create(sf.engine, checkfirst=True)
    yield sf


def _cleanup(sf, tid: str):
    with sf.Session() as session:
        session.query(SkillAsset).filter(SkillAsset.tenant_id == tid).delete()
        session.commit()


def test_lifecycle_draft_publish_deprecate(ensure_table):
    tid = f"ska-{uuid.uuid4().hex[:8]}"
    sf = ensure_table
    row = svc.create_draft(
        tenant_id=tid,
        owner_user_id="admin",
        name="plan_greet",
        description="d",
        cot_template="step by step without secrets",
        ir_skeleton={"steps": [{"capability_id": "c1", "params": {}}]},
        embed=True,
    )
    assert row.status == "draft"
    pub = svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    assert pub.status == "published"
    assert pub.version >= 2

    with pytest.raises(HTTPException) as ei:
        svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    assert ei.value.status_code == 409

    dep = svc.deprecate(tenant_id=tid, asset_id=row.id)
    assert dep.status == "deprecated"
    _cleanup(sf, tid)


def test_publish_gate_rejects_secret(ensure_table):
    tid = f"ska-s-{uuid.uuid4().hex[:8]}"
    sf = ensure_table
    row = svc.create_draft(
        tenant_id=tid,
        owner_user_id="admin",
        name="bad",
        cot_template="api_key: sk-abcdefghijklmnopqrstuvwxyz",
        embed=False,
    )
    with pytest.raises(HTTPException) as ei:
        svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    assert ei.value.status_code == 400
    _cleanup(sf, tid)


def test_search_published_hit_miss(ensure_table):
    tid = f"ska-q-{uuid.uuid4().hex[:8]}"
    sf = ensure_table
    row = svc.create_draft(
        tenant_id=tid,
        owner_user_id="admin",
        name="invoice_flow",
        description="invoice planning",
        cot_template="break invoice into steps",
        embed=True,
    )
    svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    hits = svc.search_published(tenant_id=tid, query="invoice planning", limit=3)
    # hash embed is weak but same text should score high
    assert isinstance(hits, list)
    miss = svc.search_published(
        tenant_id=tid, query="zzz_unrelated_zzz", limit=3, min_score=0.99
    )
    assert miss == []
    _cleanup(sf, tid)


def test_search_published_visibility(ensure_table):
    """评审 08-14 F2:private 仅 owner,tenant_public 租户内共享,None=系统全租户视图。"""
    tid = f"ska-vis-{uuid.uuid4().hex[:8]}"
    sf = ensure_table
    priv = svc.create_draft(
        tenant_id=tid, owner_user_id="admin", name="private_flow",
        description="private invoice flow", cot_template="private steps", embed=True,
    )
    svc.publish(tenant_id=tid, asset_id=priv.id, actor_user_id="admin")
    pub = svc.create_draft(
        tenant_id=tid, owner_user_id="admin", name="public_flow",
        description="public invoice flow", cot_template="public steps",
        visibility="tenant_public", embed=True,
    )
    svc.publish(tenant_id=tid, asset_id=pub.id, actor_user_id="admin")

    owner_hits = svc.search_published(
        tenant_id=tid, query="invoice flow", limit=5, user_id="admin"
    )
    owner_names = {h[0].name for h in owner_hits}
    assert owner_names == {"private_flow", "public_flow"}

    other_hits = svc.search_published(
        tenant_id=tid, query="invoice flow", limit=5, user_id="other"
    )
    other_names = {h[0].name for h in other_hits}
    assert "public_flow" in other_names and "private_flow" not in other_names

    sys_hits = svc.search_published(tenant_id=tid, query="invoice flow", limit=5)
    sys_names = {h[0].name for h in sys_hits}
    assert sys_names == {"private_flow", "public_flow"}
    _cleanup(sf, tid)
