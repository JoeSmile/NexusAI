"""S0 build_context 基线：节点分段耗时（Task 89 之后）。

默认 in-process 微基准（不打真实 LLM / 不要求 API）。
用法: uv run python scripts/_build_context_baseline.py
      BASELINE_SAMPLES=30 uv run python scripts/_build_context_baseline.py
"""

from __future__ import annotations

import asyncio
import gc
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.attachments.inject import inject_session_attachments
from packages.attachments.parse import AttachmentBlock
from packages.attachments.store import MemoryAttachmentStore, set_attachment_store
from packages.memory.memory_service import MemoryBundle, UnifiedMemoryService
from packages.pipeline.state import make_initial_state


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    i = min(len(ys) - 1, max(0, int(round((p / 100) * (len(ys) - 1)))))
    return ys[i]


def _summarize(name: str, xs: list[float]) -> str:
    if not xs:
        return f"{name}: no samples"
    return (
        f"{name:28s} n={len(xs)} p50={statistics.median(xs):.1f}ms "
        f"p95={_pct(xs, 95):.1f}ms min={min(xs):.1f} max={max(xs):.1f}"
    )


async def run_inprocess(n: int) -> list[str]:
    svc = UnifiedMemoryService(tenant_id="bench")
    bundle = MemoryBundle(
        hot=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好"},
        ],
        warm={f"pref:{i}": f"value-{i}" * 8 for i in range(20)},
        cold=[{"id": "c1", "summary": "上个会话谈过报销", "session_id": "s-old"}],
    )
    store = MemoryAttachmentStore()
    store.save(
        tenant_id="t1",
        session_id="s1",
        uploaded_by="u1",
        name="合同.pdf",
        media_type="application/pdf",
        size=100,
        status="ready",
        storage_path="/tmp/x",
        expired_at=None,
        blocks=[
            AttachmentBlock(
                block_index=0, kind="page", text="合同第12条 违约责任", char_count=20, page=1
            )
        ],
        attachment_id="a1",
    )
    set_attachment_store(store)
    assemble_ms: list[float] = []
    inject_ms: list[float] = []
    try:
        gc.disable()
        for _ in range(3):
            svc.assemble_prompt_block(bundle, query="报销", user_id="u1", include_hot=False)
            st = make_initial_state("t1", "u1", "s1", "看附件")
            await inject_session_attachments(st)
        for _ in range(n):
            t0 = time.perf_counter()
            svc.assemble_prompt_block(
                bundle, query="报销", user_id="u1", include_hot=False
            )
            assemble_ms.append((time.perf_counter() - t0) * 1000)
            st = make_initial_state("t1", "u1", "s1", "看附件")
            t0 = time.perf_counter()
            await inject_session_attachments(st)
            inject_ms.append((time.perf_counter() - t0) * 1000)
    finally:
        gc.enable()
        set_attachment_store(None)

    return [
        "mode=in-process (synthetic bundle + MemoryAttachmentStore)",
        f"DB_POOL_SIZE={os.getenv('DB_POOL_SIZE', '10')} "
        f"DB_MAX_OVERFLOW={os.getenv('DB_MAX_OVERFLOW', '20')}",
        "Redis/PG live=not used; HTTP live=skipped (no NEXUSAI_TOKEN gate here)",
        _summarize("assemble_prompt_block", assemble_ms),
        _summarize("inject_session_attachments", inject_ms),
        "read() per long-path turn (code model): load_memory + write_memory >= 2",
        "span names (code): pipeline.load_memory, pipeline.build_context, "
        "pipeline.model_router, pipeline.write_memory",
    ]


def main() -> None:
    n = int(os.getenv("BASELINE_SAMPLES") or "30")
    lines = asyncio.run(run_inprocess(n))
    print("\n".join(lines))
    # S5 起基线数字手写对比进 docs/build-context-s0-baseline.md，脚本只打印以免覆盖 S0。
    print("(not rewriting docs/build-context-s0-baseline.md)")


if __name__ == "__main__":
    main()
