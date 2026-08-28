"""uvicorn worker 数（Task 73 切片 3）。

``--reload`` 与多 worker 互斥，开发模式强制 1。
默认 1；生产通过 ``UVICORN_WORKERS``（或旧名 ``API_WORKERS``）显式升高。
切片 2 Redis 槽落地前禁止把默认调到 >1。
"""

from __future__ import annotations

import os


def resolve_uvicorn_workers(*, reload: bool) -> int:
    if reload:
        return 1
    raw = (os.getenv("UVICORN_WORKERS") or os.getenv("API_WORKERS") or "1").strip()
    try:
        n = int(raw)
    except ValueError:
        return 1
    return max(1, n)
