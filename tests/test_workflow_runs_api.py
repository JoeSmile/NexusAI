"""Wave D4 — run APIs + audit fields."""

from __future__ import annotations

import uuid
from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.org.scope import OrgScope
from packages.workflow.runner import start_run
from packages.database.pgvector_session import Workflow, WorkflowRun, get_pg_session
from apps.api.routers.workflow_runs import router


def test_list_and_get_run_api(monkeypatch):
    tid = f"run-api-{uuid.uuid4().hex[:8]}"
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

    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="api-wf",
            status="published",
            ir_json={"nodes": [], "edges": []},
            version="V1",
            revision=1,
            created_by=uid,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(wf)
        session.commit()
        started = start_run(
            session, tenant=tenant, org_scope=scope, workflow_id=wf.id
        )
        run_id = started["id"]

    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    monkeypatch.setattr(
        "apps.api.routers.workflow_runs.resolve_org_scope",
        lambda *a, **k: scope,
    )
    monkeypatch.setattr(
        "packages.workflow.runner.schedule_execute",
        lambda *_a, **_k: None,
    )

    client = TestClient(app)
    r = client.get("/api/runs")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert run_id in ids

    r2 = client.get(f"/api/runs/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["workflow_name"] == "api-wf"

    r3 = client.get(f"/api/runs/{run_id}/nodes")
    assert r3.status_code == 200
    assert r3.json()["run_id"] == run_id

    with sf.Session() as session:
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_draft_cannot_start(monkeypatch):
    tid = f"run-dr-{uuid.uuid4().hex[:8]}"
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
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="draft",
            status="draft",
            ir_json={"nodes": [], "edges": []},
            version="V1",
            revision=0,
            created_by=uid,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(wf)
        session.commit()
        wid = wf.id

    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    monkeypatch.setattr(
        "apps.api.routers.workflow_runs.resolve_org_scope",
        lambda *a, **k: scope,
    )

    client = TestClient(app)
    r = client.post(f"/api/workflows/{wid}/runs")
    assert r.status_code == 409

    with sf.Session() as session:
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
