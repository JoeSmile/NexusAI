# apps/api — API 进程入口（Task 75.5）

- `apps/api/app.py` — FastAPI 应用
- `apps/api/run_api.py` — uvicorn 入口（`python -m apps.api.run_api`）
- `apps/api/routers/` — HTTP 路由

兼容 shim（1 Wave）：`backend.app` / `apps.api.run_api` / `backend.routers` 仍可用；compose 可继续 `python -m apps.api.run_api`。

地图：[`docs/REPO_LAYOUT.md`](../../docs/REPO_LAYOUT.md)
