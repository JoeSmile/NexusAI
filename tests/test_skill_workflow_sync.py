"""Task 86 — skill_asset publish/deprecate syncs WorkflowIR skeletons."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from packages.capability.builtin.register import register_builtin_tools
from packages.capability.registry import CapabilityRegistry
from packages.content_ops.workflow_seed import LLM_GENERATE_IR
from packages.database.pgvector_session import SkillAsset, Workflow, get_pg_session
from packages.skill_assets import service as svc
from packages.skill_assets.workflow_sync import workflow_id_for_asset


@pytest.fixture()
def ensure_tables(monkeypatch: pytest.MonkeyPatch):
    def _fake_embed(text: str, tenant_id: str | None = None) -> list[float]:
        from packages.database.embeddings import EMBED_DIM

        return [0.0] * EMBED_DIM

    monkeypatch.setattr("packages.skill_assets.service.embed_text", _fake_embed)
    reg = CapabilityRegistry()
    register_builtin_tools(reg)
    monkeypatch.setattr(
        "packages.workflow.service.get_capability_registry",
        lambda: reg,
    )
    sf = get_pg_session()
    SkillAsset.__table__.create(sf.engine, checkfirst=True)
    Workflow.__table__.create(sf.engine, checkfirst=True)
    yield sf


def _cleanup(sf, tid: str) -> None:
    with sf.Session() as session:
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.query(SkillAsset).filter(SkillAsset.tenant_id == tid).delete()
        session.commit()


def test_steps_skeleton_publish_does_not_create_workflow(ensure_tables) -> None:
    tid = f"ska-st-{uuid.uuid4().hex[:8]}"
    sf = ensure_tables
    row = svc.create_draft(
        tenant_id=tid,
        owner_user_id="admin",
        name="template_skill",
        cot_template="safe template without secrets",
        ir_skeleton={"steps": [{"capability_id": "c1", "params": {}}]},
        embed=False,
    )
    pub = svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    assert pub.status == "published"
    stats = dict(pub.usage_stats or {})
    assert not stats.get("workflow_id")
    wid = workflow_id_for_asset(row.id)
    with sf.Session() as session:
        assert session.query(Workflow).filter(Workflow.id == wid).one_or_none() is None
    _cleanup(sf, tid)


def test_nodes_skeleton_publish_creates_and_deprecate_archives(ensure_tables) -> None:
    tid = f"ska-nd-{uuid.uuid4().hex[:8]}"
    sf = ensure_tables
    row = svc.create_draft(
        tenant_id=tid,
        owner_user_id="admin",
        name="llm_gen_skill",
        cot_template="generate from user topic without secrets",
        ir_skeleton=dict(LLM_GENERATE_IR),
        embed=False,
    )
    pub = svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    wid = str((pub.usage_stats or {}).get("workflow_id") or "")
    assert wid == workflow_id_for_asset(row.id)
    with sf.Session() as session:
        wf = session.query(Workflow).filter(Workflow.id == wid).one()
        assert wf.status == "published"
        assert wf.tenant_id == tid
        assert (wf.ir_json or {}).get("output_node_id") == "gen"

    again_id = workflow_id_for_asset(row.id)
    with sf.Session() as session:
        wf = session.query(Workflow).filter(Workflow.id == again_id).one()
        wf.ir_json = dict(LLM_GENERATE_IR)
        session.commit()

    dep = svc.deprecate(tenant_id=tid, asset_id=row.id)
    assert dep.status == "deprecated"
    assert "workflow_id" not in dict(dep.usage_stats or {})
    with sf.Session() as session:
        wf = session.query(Workflow).filter(Workflow.id == wid).one()
        assert wf.status == "archived"
    _cleanup(sf, tid)


def test_v1_sync_does_not_update_existing_workflow(ensure_tables) -> None:
    from packages.skill_assets.workflow_sync import sync_skill_workflow_on_publish

    tid = f"ska-once-{uuid.uuid4().hex[:8]}"
    sf = ensure_tables
    row = svc.create_draft(
        tenant_id=tid,
        owner_user_id="admin",
        name="llm_gen_skill",
        cot_template="generate from user topic without secrets",
        ir_skeleton=dict(LLM_GENERATE_IR),
        embed=False,
    )
    pub = svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    wid = str((pub.usage_stats or {}).get("workflow_id") or "")
    with sf.Session() as session:
        wf = session.query(Workflow).filter(Workflow.id == wid).one()
        wf.ir_json = {"frozen": True}
        session.commit()
        asset = session.query(SkillAsset).filter(SkillAsset.id == row.id).one()
        again = sync_skill_workflow_on_publish(
            session, asset=asset, created_by="admin"
        )
        session.commit()
        wf = session.query(Workflow).filter(Workflow.id == wid).one()
        assert again == wid
        assert wf.ir_json == {"frozen": True}
    _cleanup(sf, tid)


def test_invalid_nodes_skeleton_rejects_publish(ensure_tables) -> None:
    tid = f"ska-bad-{uuid.uuid4().hex[:8]}"
    sf = ensure_tables
    row = svc.create_draft(
        tenant_id=tid,
        owner_user_id="admin",
        name="bad_nodes",
        cot_template="safe template without secrets",
        ir_skeleton={
            "ir_schema": "1",
            "nodes": [
                {
                    "node_id": "x",
                    "kind": "capability",
                    "capability_id": "does.not.exist",
                    "params": {},
                }
            ],
            "edges": [],
        },
        embed=False,
    )
    with pytest.raises(HTTPException) as ei:
        svc.publish(tenant_id=tid, asset_id=row.id, actor_user_id="admin")
    assert ei.value.status_code == 400
    _cleanup(sf, tid)
