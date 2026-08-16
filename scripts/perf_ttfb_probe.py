"""性能实测: 图执行耗时(首 token 前的本地部分)。"""
import asyncio
import time

from backend.pipeline.graph import compiled_graph
from backend.pipeline.state import make_initial_state


async def main() -> None:
    state = make_initial_state(
        tenant_id="acme",
        user_id="u1",
        session_id="perf-test",
        message="帮我分析一下最近教育行业的政策热点，写一份口播稿",
    )
    state["user_context"] = {
        "tenant_id": "acme",
        "user_id": "u1",
        "permissions": [],
        "role": "user",
    }
    state["stream_mode"] = True

    t0 = time.perf_counter()
    final = await compiled_graph.ainvoke(state)
    t1 = time.perf_counter()
    print(f"图执行耗时(stream_mode, task_plan 已跳过): {t1 - t0:.3f}s")
    print(
        f"finish_reason={final.get('finish_reason')} "
        f"task_plan={final.get('task_plan')} "
        f"intent={final.get('intent')}"
    )


if __name__ == "__main__":
    asyncio.run(main())
