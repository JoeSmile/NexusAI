"""Wave C2 — optimistic lock focused cases."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from packages.auth.models import TenantContext
from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)
from packages.capability.registry import CapabilityRegistry
from backend.core.org.scope import OrgScope
from packages.workflow import service as wf_svc
from backend.database.pgvector_session import Workflow, get_pg_session


@pytest.fixture
def ctx():
    tid = f"wf-ol-{uuid.uuid4().hex[:10]}"
    tenant = TenantContext(tid, "admin1", "tenant_admin", ["*"], False)
    scope = OrgScope(
        tenant_id=tid,
        user_id="admin1",
        platform_role="tenant_admin",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="rag-ask",
            name="RAG",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True},
            permission="chat:write",
        )
    )
    yield tenant, scope, reg, tid
    sf = get_pg_session()
    with sf.Session() as session:
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_double_publish_second_409(ctx, monkeypatch):
    tenant, scope, reg, _tid = ctx
    monkeypatch.setattr(
        "packages.workflow.service.get_capability_registry", lambda: reg
    )
    sf = get_pg_session()
    with sf.Session() as session:
        created = wf_svc.create_workflow(
            session,
            tenant=tenant,
            org_scope=scope,
            name="P",
            org_unit_id="ou-1",
            ir_data=None,
        )
        wf_svc.publish_workflow(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=created["id"],
        )
        with pytest.raises(HTTPException) as ei:
            wf_svc.publish_workflow(
                session,
                tenant=tenant,
                org_scope=scope,
                workflow_id=created["id"],
            )
        assert ei.value.status_code == 409


def test_publish_revision_mismatch(ctx, monkeypatch):
    tenant, scope, reg, _tid = ctx
    monkeypatch.setattr(
        "packages.workflow.service.get_capability_registry", lambda: reg
    )
    sf = get_pg_session()
    with sf.Session() as session:
        created = wf_svc.create_workflow(
            session,
            tenant=tenant,
            org_scope=scope,
            name="P2",
            org_unit_id="ou-1",
            ir_data=None,
        )
        with pytest.raises(HTTPException) as ei:
            wf_svc.publish_workflow(
                session,
                tenant=tenant,
                org_scope=scope,
                workflow_id=created["id"],
                base_revision=99,
            )
        assert ei.value.status_code == 409
