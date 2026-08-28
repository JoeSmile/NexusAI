"""Wave D review 补测 — CAS 败者不污染胜者 + 并发上限 429（负向，验收标准要求）。"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from packages.auth.models import TenantContext
from packages.org.scope import OrgScope
from packages.workflow.runner import execute_run, start_run
from backend.database.pgvector_session import Workflow, WorkflowRun, get_pg_session


def _mk_run(
    session, *, tid: str, uid: str, status: str, workflow_id: str | None = None
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
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(run)
    session.commit()
    return run


def _tenant_scope(tid: str) -> tuple[TenantContext, OrgScope]:
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


@pytest.mark.asyncio
async def test_cas_loser_does_not_fail_winner():
    """双 execute 同 run：败者 CAS 失败必须直接退出，不得把胜者的 running 标 failed。

    review 修复（2026-08-12）：CAS rowcount!=1 分支从 raise HTTPException 改为 return——
    原实现会经 _fail_run 把已 running 的胜者标 failed 并写错误审计。
    """
    tid = f"cas-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        run = _mk_run(session, tid=tid, uid="u1", status="running")  # 胜者已持有
        run_id = run.id  # commit 后属性过期;须在 session 存活内读取
    await execute_run(run_id)  # 败者：CAS 失败应直接 return
    with sf.Session() as session:
        row = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert row.status == "running"
        assert row.error_code is None


def test_start_run_429_when_two_running():
    """每 (tenant, acting_user) 最多 2 个 running 根 run → 429 RUN_CONCURRENCY_LIMIT。"""
    tid = f"r429-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="wf",
            status="published",
            ir_json={"nodes": []},
            version="V1",
            revision=1,
            created_by="u1",
        )
        session.add(wf)
        for _ in range(2):
            _mk_run(session, tid=tid, uid="u1", status="running", workflow_id=wf.id)
        session.commit()
        tenant, scope = _tenant_scope(tid)
        with pytest.raises(HTTPException) as ei:
            start_run(session, tenant=tenant, org_scope=scope, workflow_id=wf.id)
        assert ei.value.status_code == 429
