"""Wave D2 — node idempotency skip on succeeded."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.auth.models import TenantContext
from backend.core.org.scope import OrgScope
from backend.core.workflow.runner import _execute_node
from backend.database.pgvector_session import WorkflowRun, WorkflowRunNode, get_pg_session


@pytest.mark.asyncio
async def test_succeeded_node_skips_invoke():
    tid = f"idemp-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    sf = get_pg_session()
    with sf.Session() as session:
        run = WorkflowRun(
            id=run_id,
            tenant_id=tid,
            workflow_id=str(uuid.uuid4()),
            org_unit_id="ou-1",
            status="running",
            ir_snapshot={"nodes": []},
            workflow_version="V1",
            workflow_revision=1,
            acting_user_id="u1",
            credential_kind="human_session",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(run)
        session.add(
            WorkflowRunNode(
                id=str(uuid.uuid4()),
                run_id=run_id,
                node_id="n1",
                status="succeeded",
                attempt=1,
                idempotency_key=f"{run_id}:n1",
                output_json={"result": {"answer": "cached"}, "evidence": []},
                finished_at=datetime.utcnow(),
            )
        )
        session.commit()

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
        with patch(
            "backend.core.workflow.runner.invoke", new_callable=AsyncMock
        ) as inv:
            await _execute_node(
                session,
                run=run,
                node={"node_id": "n1", "capability_id": "rag-ask", "params": {}},
                tenant=tenant,
                org_scope=scope,
            )
            inv.assert_not_called()

        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.commit()
