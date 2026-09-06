"""Task 1b — workflow Skill → published Workflow bind + start_run."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from packages.auth.models import TenantContext
from packages.database.pgvector_session import Workflow, WorkflowRun, get_pg_session
from packages.org.scope import OrgScope
from packages.skills.registry import SKILL_REGISTRY
from packages.workflow.ir import WorkflowIR


@pytest.fixture()
def pg_workflows():
    sf = get_pg_session()
    try:
        with sf.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("postgres unavailable")
    Workflow.__table__.create(sf.engine, checkfirst=True)
    WorkflowRun.__table__.create(sf.engine, checkfirst=True)
    yield sf


def test_prefer_hotspot_script_carrier_for_koubo() -> None:
    from packages.pipeline.chat_workflow_bridge import prefer_hotspot_script_carrier

    assert prefer_hotspot_script_carrier("写个口播稿", "content_creation")
    assert prefer_hotspot_script_carrier("帮我抓下热点", None)
    assert not prefer_hotspot_script_carrier("怎么退款", "after_sales")


def test_hotspot_logical_key_resolves_tenant_published_not_uuid_on_class(
    pg_workflows,
) -> None:
    from packages.skills.workflow_bind import resolve_workflow_id

    skill = SKILL_REGISTRY["hotspot_script"]
    assert skill.workflow_asset_id == "builtin:hotspot"
    assert "-" not in (skill.workflow_asset_id or "")

    tid = f"sk-hs-{uuid.uuid4().hex[:8]}"
    with pg_workflows.Session() as session:
        wid = resolve_workflow_id(session, tenant_id=tid, skill=skill)
        session.commit()
        row = session.query(Workflow).filter(Workflow.tenant_id == tid, Workflow.id == wid).one()
        assert row.status == "published"
        assert row.ir_json  # hotspot.dig seed IR
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_quote_proposal_ir_upserts_published_and_start_run(pg_workflows) -> None:
    from packages.skills.workflow_bind import resolve_workflow_id
    from packages.workflow.run_lifecycle import start_run

    skill = SKILL_REGISTRY["quote_proposal"]
    tid = f"sk-qp-{uuid.uuid4().hex[:8]}"
    uid = "admin1"
    tenant = TenantContext(tid, uid, "tenant_admin", ["*"], False)
    scope = OrgScope(
        tenant_id=tid,
        user_id=uid,
        platform_role="tenant_admin",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )

    with pg_workflows.Session() as session:
        wid = resolve_workflow_id(session, tenant_id=tid, skill=skill)
        session.commit()
        row = session.query(Workflow).filter(Workflow.tenant_id == tid, Workflow.id == wid).one()
        assert row.status == "published"
        expected = WorkflowIR.model_validate(skill.workflow_ir).model_dump(mode="json")
        assert row.ir_json == expected
        row.org_unit_id = "ou-1"
        session.commit()

        started = start_run(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=wid,
            run_inputs={"sku": "A1", "qty": "2"},
        )
        assert started is not None
        assert started.get("id")

        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_ensure_skill_workflows_published_covers_four(pg_workflows) -> None:
    from packages.skills.workflow_bind import ensure_skill_workflows_published

    tid = f"sk-all-{uuid.uuid4().hex[:8]}"
    with pg_workflows.Session() as session:
        ids = ensure_skill_workflows_published(session, tenant_id=tid)
        session.commit()
        assert set(ids) >= {
            "quote_proposal",
            "hotspot_script",
            "social_copy",
            "weekly_report",
        }
        assert ids["hotspot_script"] != ids["quote_proposal"]
        second = ensure_skill_workflows_published(session, tenant_id=tid)
        session.commit()
        assert second == ids
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
