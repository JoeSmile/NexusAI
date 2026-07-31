"""租户中间件 — 注入 trace_id 和 tenant_id"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware


class TenantMiddleware(BaseHTTPMiddleware):
    """注入 request.state.trace_id + 提取 tenant_id"""

    async def dispatch(self, request, call_next):
        request.state.trace_id = f"tr_{uuid.uuid4().hex[:12]}"

        tenant_context = getattr(request.state, "tenant_context", None)
        request.state.tenant_id = (
            tenant_context.tenant_id if tenant_context else "default"
        )

        response = await call_next(request)
        # auth Depends 在 call_next 内注入 tenant_context 后再回填
        tenant_context = getattr(request.state, "tenant_context", None)
        if tenant_context is not None:
            request.state.tenant_id = tenant_context.tenant_id
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response
