"""探针: workflow run 完成后 node output 结构(runHotspotDigInPlace 的 countFromNodes 能否解析)。"""
import asyncio

from packages.auth.models import TenantContext
from packages.org.scope import resolve_org_scope
from packages.workflow import runner as run_svc
from packages.database.pgvector_session import Workflow, get_pg_session


async def main() -> None:
    sf = get_pg_session()
    with sf.Session() as session:
        wf = (
            session.query(Workflow)
            .filter(
                Workflow.tenant_id == "acme",
                Workflow.name == "内置·抓取相关热点",
            )
            .first()
        )
        print(f"workflow: {wf.id if wf else None} status={wf.status if wf else None}")
        tenant = TenantContext(
            tenant_id="acme",
            user_id="g7a_admin_5bc20c4b",
            role="tenant_admin",
            extra_permissions=["chat:write", "content:*"],
            is_cross_tenant=False,
        )
        scope = resolve_org_scope(session, tenant_id="acme", user_id="g7a_admin_5bc20c4b", platform_role="tenant_admin", is_cross_tenant=False)
        started = run_svc.start_run(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=wf.id,
            run_inputs={"topic": "帮我抓下热点", "adapter": "topic_agent", "save": True, "platform": "chat"},
        )
        rid = started["id"]
        print(f"run: {rid}")

    run_svc.schedule_execute(rid)

    for _ in range(60):
        await asyncio.sleep(1)
        with sf.Session() as session:
            from packages.database.pgvector_session import WorkflowRun

            row = session.query(WorkflowRun).filter(WorkflowRun.id == rid).first()
            if row and row.status in ("succeeded", "failed", "cancelled", "suspended"):
                print(f"run status: {row.status}")
                if row.status != "succeeded":
                    print(f"  error: {row.error_code} {row.error_message}")
                break
    else:
        print("run 超时未终态")

    from packages.database.pgvector_session import WorkflowRun, WorkflowRunNode

    with sf.Session() as session:
        nodes = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == rid)
            .order_by(WorkflowRunNode.started_at.asc().nullsfirst())
            .all()
        )
    print(f"nodes: {len(nodes)}")
    for n in nodes:
        out = n.output
        print(f"  node={n.node_id} kind={getattr(n, 'kind', '?')} output_type={type(out).__name__}")
        if isinstance(out, dict):
            print(f"    output keys: {list(out.keys())[:10]}")
            for k, v in out.items():
                print(f"      {k}: {type(v).__name__} = {str(v)[:90]}")
        else:
            print(f"    output: {str(out)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
