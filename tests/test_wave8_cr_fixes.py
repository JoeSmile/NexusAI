"""Wave 8 CR fixes — cancel→wake, recover, orphan, exact invalidate."""

from __future__ import annotations

import uuid
from datetime import datetime

from packages.auth.models import TenantContext
from backend.core.org.scope import OrgScope
from packages.workflow.runner import cancel_run, recover_waiting_child_parents, wake_parent
from backend.database.pgvector_session import (
    Workflow,
    WorkflowRun,
    WorkflowRunNode,
    get_pg_session,
)
from packages.pipeline.exact_cache import exact_cache_key, invalidate_exact_cache
from backend.routers.workflow_runs import _run_dict


def _tenant(tid: str) -> tuple[TenantContext, OrgScope]:
    tenant = TenantContext(tid, "u1", "tenant_admin", ["*"], False)
    scope = OrgScope(
        tenant_id=tid,
        user_id="u1",
        platform_role="tenant_admin",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )
    return tenant, scope


def test_cancel_child_wakes_parent() -> None:
    """1A: cancel child → parent waiting_child node failed (propagate)."""
    tid = f"c1a-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    tenant, scope = _tenant(tid)
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="p",
            status="published",
            ir_json={"nodes": []},
            version="V1",
            revision=1,
            created_by="u1",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(wf)
        parent = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            workflow_id=wf.id,
            org_unit_id="ou-1",
            status="running",
            ir_snapshot={"nodes": [{"node_id": "n_sub", "kind": "workflow"}]},
            workflow_version="V1",
            workflow_revision=1,
            acting_user_id="u1",
            credential_kind="human_session",
            composition_depth=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(parent)
        session.flush()
        child = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            workflow_id=wf.id,
            org_unit_id="ou-1",
            status="running",
            ir_snapshot={"nodes": []},
            workflow_version="V1",
            workflow_revision=1,
            acting_user_id="u1",
            credential_kind="human_session",
            parent_run_id=parent.id,
            parent_node_id="n_sub",
            composition_depth=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(child)
        session.add(
            WorkflowRunNode(
                id=str(uuid.uuid4()),
                run_id=parent.id,
                node_id="n_sub",
                status="waiting_child",
                attempt=1,
                idempotency_key=f"{parent.id}:n_sub",
            )
        )
        session.commit()
        pid, cid = parent.id, child.id

        cancel_run(session, tenant=tenant, org_scope=scope, run_id=cid)

        child2 = session.query(WorkflowRun).filter(WorkflowRun.id == cid).one()
        assert child2.status == "cancelled"
        node = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.idempotency_key == f"{pid}:n_sub")
            .one()
        )
        assert node.status == "failed"
        parent2 = session.query(WorkflowRun).filter(WorkflowRun.id == pid).one()
        assert parent2.status == "failed"

        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == pid).delete()
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_recover_waiting_child_when_child_already_terminal(monkeypatch) -> None:
    """2A: startup recover wakes parent if child finished without wake."""
    monkeypatch.setattr(
        "packages.workflow.run_lifecycle.schedule_resume_or_continue",
        lambda *_a, **_k: None,
    )
    tid = f"c2a-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="p",
            status="published",
            ir_json={"nodes": []},
            version="V1",
            revision=1,
            created_by="u1",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(wf)
        parent = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            workflow_id=wf.id,
            org_unit_id="ou-1",
            status="running",
            ir_snapshot={"nodes": [{"node_id": "n_sub"}]},
            workflow_version="V1",
            workflow_revision=1,
            acting_user_id="u1",
            credential_kind="human_session",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(parent)
        session.flush()
        child = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            workflow_id=wf.id,
            org_unit_id="ou-1",
            status="succeeded",
            ir_snapshot={"nodes": []},
            workflow_version="V1",
            workflow_revision=1,
            acting_user_id="u1",
            credential_kind="human_session",
            parent_run_id=parent.id,
            parent_node_id="n_sub",
            composition_depth=1,
            finished_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(child)
        session.add(
            WorkflowRunNode(
                id=str(uuid.uuid4()),
                run_id=parent.id,
                node_id="n_sub",
                status="waiting_child",
                attempt=1,
                idempotency_key=f"{parent.id}:n_sub",
            )
        )
        session.commit()
        pid = parent.id

    n = recover_waiting_child_parents()
    assert n >= 1
    with sf.Session() as session:
        node = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.idempotency_key == f"{pid}:n_sub")
            .one()
        )
        assert node.status == "succeeded"
        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == pid).delete()
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_orphan_flag_when_parent_failed() -> None:
    child = WorkflowRun(
        id="c",
        tenant_id="t",
        workflow_id="w",
        org_unit_id="ou",
        status="running",
        ir_snapshot={},
        workflow_version="V1",
        workflow_revision=1,
        acting_user_id="u",
        parent_run_id="p",
    )
    assert _run_dict(child, parent_status="failed")["orphan"] is True
    assert _run_dict(child, parent_status="cancelled")["orphan"] is True
    assert _run_dict(child, parent_status="running")["orphan"] is False
    root = WorkflowRun(
        id="r",
        tenant_id="t",
        workflow_id="w",
        org_unit_id="ou",
        status="running",
        ir_snapshot={},
        workflow_version="V1",
        workflow_revision=1,
        acting_user_id="u",
    )
    assert _run_dict(root, parent_status="failed")["orphan"] is False


def test_exact_cache_key_shape() -> None:
    assert exact_cache_key("t", "u", "abc") == "exact:t:u:abc"


def test_invalidate_exact_cache_noop_empty() -> None:
    assert invalidate_exact_cache("t", "u", "") is False


def test_wake_parent_importable() -> None:
    assert callable(wake_parent)
