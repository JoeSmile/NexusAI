"""TTFB 拆解: 图执行耗时 vs LLM 首 token 耗时(真实 record 环境)。"""
import asyncio
import time

from backend.core.harness import LLMHarness
from packages.pipeline.graph import compiled_graph
from packages.pipeline.state import make_initial_state


async def main() -> None:
    # 1. 图执行(stream_mode, 长路径)
    state = make_initial_state(
        tenant_id="acme",
        user_id="u1",
        session_id="ttfb-probe",
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
    print(f"[1] 图执行(stream_mode): {t1 - t0:.3f}s  finish={final.get('finish_reason')}")

    # 2. LLM 首 token(真实 deepseek)
    prompt = final.get("assembled_prompt") or final.get("message") or "你好"
    h = LLMHarness()
    model = final.get("selected_model") or "deepseek-v4-flash"
    t2 = time.perf_counter()
    first = None
    n = 0
    async for tok in h.stream(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        tenant_id="acme",
        max_tokens=200,
    ):
        if first is None:
            first = time.perf_counter()
            print(f"[2] LLM 首 token: {first - t2:.3f}s (model={model})")
        n += 1
    t3 = time.perf_counter()
    print(f"[3] LLM 完整 200 tokens: {t3 - t2:.3f}s tokens~{n}")
    print(f"[4] 理论 TTFB = [1]+[2] = {t1 - t0 + (first - t2):.3f}s")


if __name__ == "__main__":
    asyncio.run(main())
