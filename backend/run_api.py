"""API 入口：按 UVICORN_WORKERS 起进程；--reload 强制 1 worker。"""

from __future__ import annotations

import os

import uvicorn

from backend.core.uvicorn_workers import resolve_uvicorn_workers


def main() -> None:
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("UVICORN_RELOAD", "").strip().lower() in ("1", "true", "yes")
    workers = resolve_uvicorn_workers(reload=reload)
    uvicorn.run(
        "backend.app:app",
        host=host,
        port=port,
        reload=reload,
        workers=1 if reload else workers,
    )


if __name__ == "__main__":
    main()
