"""Wave C2 — workflow CRUD against real DB."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from packages.capability.registry import CapabilityRegistry
from backend.core.org.scope import OrgScope
from packages.workflow import service as wf_svc
from backend.database.pgvector_session import Workflow, get_pg_session
from apps.api.routers.workflows import router


@pytest.fixture
def tenant_id() -> str:
    return f"wf-c2-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def admin(tenant_id: str) -> TenantContext:
    return TenantContext(tenant_id, "admin1", "tenant_admin", ["*"], False)


@pytest.fixture
def user(tenant_id: str) -> TenantContext:
    return TenantContext(tenant_id, "user1", "user", [], False)


@pytest.fixture
def org_scope(tenant_id: str) -> OrgScope:
    return OrgScope(
        tenant_id=tenant_id,
        user_id="admin1",
        platform_role="tenant_admin",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset({"member"}),
        is_cross_tenant=False,
    )


@pytest.fixture
def cap_reg(monkeypatch) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="rag-ask",
            name="RAG Ask",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True},
            permission="chat:write",
            param_spec={"query": {"type": "string", "required": True}},
        )
    )
    reg.register(
        CapabilitySpec(
            id="admin-tool",
            name="Admin Tool",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True},
            permission="admin:*",
            tenant_id="other-tenant",
        )
    )
    reg.register(
        CapabilitySpec(
            id="visible-not-permitted",
            name="VPN",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True},
            permission="admin:*",
            tenant_id="*",
        )
    )
    monkeypatch.setattr(
        "packages.workflow.service.get_capability_registry", lambda: reg
    )
    return reg


@pytest.fixture(autouse=True)
def _cleanup(tenant_id: str):
    yield
    sf = get_pg_session()
    with sf.Session() as session:
        session.query(Workflow).filter(Workflow.tenant_id == tenant_id).delete()
        session.commit()


def test_create_patch_publish_fork(admin, org_scope, cap_reg):
    sf = get_pg_session()
    with sf.Session() as session:
        created = wf_svc.create_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            name="Demo",
            org_unit_id=None,
            ir_data={"ir_schema": "1", "nodes": [], "edges": []},
        )
        assert created["status"] == "draft"
        assert created["org_unit_id"] == "ou-1"
        assert created["revision"] == 0

        patched = wf_svc.patch_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            workflow_id=created["id"],
            base_revision=0,
            ir_data={
                "ir_schema": "1",
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "rag-ask",
                        "params": {"query": "hello"},
                    }
                ],
                "edges": [],
            },
        )
        assert patched["revision"] == 1
        assert len(patched["ir"]["nodes"]) == 1

        published = wf_svc.publish_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            workflow_id=created["id"],
            base_revision=1,
        )
        assert published["status"] == "published"
        assert published["revision"] == 2

        with pytest.raises(HTTPException) as ei:
            wf_svc.patch_workflow(
                session,
                tenant=admin,
                org_scope=org_scope,
                workflow_id=created["id"],
                base_revision=2,
                name="Nope",
            )
        assert ei.value.status_code == 409

        fork = wf_svc.fork_draft(
            session,
            tenant=admin,
            org_scope=org_scope,
            workflow_id=created["id"],
        )
        assert fork["status"] == "draft"
        assert fork["forked_from_id"] == created["id"]
        assert fork["revision"] == 0

        published2 = wf_svc.publish_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            workflow_id=fork["id"],
        )
        assert published2["status"] == "published"

        src = wf_svc.get_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            workflow_id=created["id"],
        )
        assert src["status"] == "archived"


def test_optimistic_lock_conflict(admin, org_scope, cap_reg):
    sf = get_pg_session()
    with sf.Session() as session:
        created = wf_svc.create_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            name="Lock",
            org_unit_id="ou-1",
            ir_data=None,
        )
        wf_svc.patch_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            workflow_id=created["id"],
            base_revision=0,
            name="A",
        )
        with pytest.raises(HTTPException) as ei:
            wf_svc.patch_workflow(
                session,
                tenant=admin,
                org_scope=org_scope,
                workflow_id=created["id"],
                base_revision=0,
                name="B",
            )
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "WF_021"


def test_delete_draft_only(admin, org_scope, cap_reg):
    sf = get_pg_session()
    with sf.Session() as session:
        created = wf_svc.create_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            name="Del",
            org_unit_id="ou-1",
            ir_data=None,
        )
        wf_svc.publish_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            workflow_id=created["id"],
        )
        with pytest.raises(HTTPException) as ei:
            wf_svc.delete_workflow(
                session,
                tenant=admin,
                org_scope=org_scope,
                workflow_id=created["id"],
            )
        assert ei.value.status_code == 409


def test_user_cannot_create(user, org_scope, cap_reg):
    sf = get_pg_session()
    with sf.Session() as session:
        with pytest.raises(HTTPException) as ei:
            wf_svc.create_workflow(
                session,
                tenant=user,
                org_scope=org_scope,
                name="X",
                org_unit_id=None,
                ir_data=None,
            )
        assert ei.value.status_code == 403


def test_invisible_capability_rejected(admin, org_scope, cap_reg):
    sf = get_pg_session()
    with sf.Session() as session:
        with pytest.raises(HTTPException) as ei:
            wf_svc.create_workflow(
                session,
                tenant=admin,
                org_scope=org_scope,
                name="Bad",
                org_unit_id="ou-1",
                ir_data={
                    "nodes": [
                        {
                            "node_id": "n1",
                            "capability_id": "admin-tool",
                            "params": {},
                        }
                    ]
                },
            )
        assert ei.value.status_code == 400
        assert ei.value.detail["code"] == "WF_012"


def test_visible_but_not_permitted_can_save(admin, org_scope, cap_reg):
    """保存不要求可调 — permission=admin:* 仍可写入 IR。"""
    sf = get_pg_session()
    with sf.Session() as session:
        created = wf_svc.create_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            name="VPN",
            org_unit_id="ou-1",
            ir_data={
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "visible-not-permitted",
                        "params": {},
                    }
                ]
            },
        )
        assert created["ir"]["nodes"][0]["capability_id"] == "visible-not-permitted"


def test_api_list_and_get(admin, org_scope, cap_reg, monkeypatch):
    sf = get_pg_session()
    with sf.Session() as session:
        created = wf_svc.create_workflow(
            session,
            tenant=admin,
            org_scope=org_scope,
            name="API",
            org_unit_id="ou-1",
            ir_data=None,
        )

    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def _auth() -> TenantContext:
        return admin

    app.dependency_overrides[verify_human_or_legacy_key] = _auth

    monkeypatch.setattr(
        "apps.api.routers.workflows.resolve_org_scope",
        lambda *a, **k: org_scope,
    )

    client = TestClient(app)
    r = client.get("/api/workflows")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert created["id"] in ids

    r2 = client.get(f"/api/workflows/{created['id']}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "API"
