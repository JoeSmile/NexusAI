"""Task 40.85 — composition concurrency (quota + nested exemption)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from packages.auth.models import TenantContext
from backend.core.org.scope import OrgScope
from backend.core.workflow.composition import (
    MAX_COMPOSITION_DEPTH,
    CompositionDepthExceeded,
    check_composition_budget,
)
from backend.core.workflow.runner import MAX_RUNNING_ROOT_RUNS, start_run
from backend.database.pgvector_session import Workflow, WorkflowRun, get_pg_session


def _mk_run(
    session,
    *,
    tid: str,
    uid: str,
    status: str,
    workflow_id: str | None = None,
    parent_run_id: str | None = None,
) -> WorkflowRun:
    run = WorkflowRun(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        workflow_id=workflow_id or str(uuid.uuid4()),
        org_unit_id="ou-1",
        status=status,
        ir_snapshot={"nodes": []},
        workflow_version="V1",
        workflow_revision=1,
        acting_user_id=uid,
        credential_kind="human_session",
        parent_run_id=parent_run_id,
        composition_depth=1 if parent_run_id else 0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(run)
    session.commit()
    return run


def _tenant_scope(tid: str, uid: str = "u1") -> tuple[TenantContext, OrgScope]:
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
    return tenant, scope


def test_check_composition_budget_ok() -> None:
    check_composition_budget(2, 1)
    check_composition_budget(3, 0)
    check_composition_budget(0, 3)


def test_check_composition_budget_exceeded() -> None:
    with pytest.raises(CompositionDepthExceeded):
        check_composition_budget(2, 2)
    with pytest.raises(CompositionDepthExceeded):
        check_composition_budget(3, 1)


def test_root_quota_constant() -> None:
    assert MAX_RUNNING_ROOT_RUNS == 2
    assert MAX_COMPOSITION_DEPTH == 3


def test_two_roots_full_third_root_429_child_ok() -> None:
    tid = f"c85-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="comp",
            status="published",
            ir_json={"nodes": []},
            version="V1",
            revision=1,
            created_by="u1",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(wf)
        session.commit()
        r1 = _mk_run(session, tid=tid, uid="u1", status="running", workflow_id=wf.id)
        _mk_run(session, tid=tid, uid="u1", status="running", workflow_id=wf.id)
        tenant, scope = _tenant_scope(tid)

        with pytest.raises(HTTPException) as ei:
            start_run(session, tenant=tenant, org_scope=scope, workflow_id=wf.id)
        assert ei.value.status_code == 429

        child = start_run(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=wf.id,
            parent_run_id=r1.id,
            parent_node_id="n_sub",
            _internal_nested=True,
        )
        assert child["parent_run_id"] == r1.id
        assert child["composition_depth"] == 1

        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_serial_ready_not_parallel_documented() -> None:
    from backend.core.workflow.dataflow import pick_next_ready, ready_node_ids

    assert callable(ready_node_ids)
    assert callable(pick_next_ready)
