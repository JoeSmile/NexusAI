"""探针: chat→bridge 触发 + hotspot run 执行(问题1/2 复测)。"""
import asyncio

from packages.pipeline.nodes.task_plan import task_plan
from packages.pipeline.state import make_initial_state


async def main() -> None:
    state = make_initial_state(
        tenant_id="acme",
        user_id="admin",
        session_id="bridge-probe",
        message="帮我抓下热点",
    )
    state["user_context"] = {
        "tenant_id": "acme",
        "user_id": "admin",
        "permissions": ["chat:write", "content:*"],
        "role": "tenant_admin",
    }
    state["intent"] = "knowledge_query"
    state["intent_confidence"] = 0.6
    state["stream_mode"] = True

    out = await task_plan(state)
    print(f"triggered_run={out.get('triggered_run')}")
    if out.get("triggered_run"):
        print(f"run_id={out['triggered_run'].get('id')} wf={out['triggered_run'].get('workflow_id')}")


if __name__ == "__main__":
    asyncio.run(main())
