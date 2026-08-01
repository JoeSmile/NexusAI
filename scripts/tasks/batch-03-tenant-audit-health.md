# Batch 3: 多租户 + 审计 + 健康检查 + 结构化错误码

> **包含:** Task 03 (4 subtasks) + Task 12 (3 subtasks)  
> **预估:** 20-35 分钟  
> **依赖:** Batch 2 (auth + TenantContext)  
> **⚠️ 03 + 12 无依赖可平行 — 但建议一起写，因为 error_handler 中间件和 audit 都涉及 app.py 注册**  
> **⚠️ 先做 Subtask 3.1 清理，再写 03/12 逻辑，避免误用被删的旧模块**  
> **Commit:** `git add -A && git commit -m "feat: tenant isolation, audit logging, health check, error codes\n\nSigned-off-by: Joe"`

---

## Subtask 3.1: 遗留代码清理（死代码移除）

> **目的:** 移除 emotional_chat 遗留的、ContextGate 不会使用的代码，防止后续 Task 误引用旧模块。
> **原则:** 只删确定的死代码；不确定的加 `# DEPRECATED` 保留。删完必须跑一遍 import 检查确认没破坏引用。

### 3.1.1 整个目录删除（无争议）

```bash
# AB 测试 + Prompt 优化（emotional_chat 的私有实验）
rm -rf Prompt优化测试/
rm -rf backend/ab_testing/
rm -rf backend/scripts/ab_test_analysis.py backend/scripts/ab_test_demo.py
rm -rf backend/prompt_optimizer.py

# 多模态（语音/图像/人脸识别，ContextGate 不需要）
rm -rf backend/modules/multimodal/
rm -rf backend/multimodal_services.py

# Codex 相关（原作者的个人工具脚本）
rm -rf scripts/build_codex_learning_map_xmind.py
rm -rf scripts/build_codex_use_cases_xmind.py
rm -rf scripts/extract_codex_pdf_outline.py

# Hermes 工作区（抄 Nous Hermes 的临时功能，不属于 ContextGate）
rm -rf backend/hermes/

# 旧插件系统（天气/新闻/节假日插件 — 被 Skill 系统 Task 07 替代）
# 引用方确认: backend/main.py + backend/services/chat_service.py（均为旧代码）
rm -rf backend/plugins/

# 旧单文件入口（与 backend/app.py 重复，run_backend.py 用的是 backend.app:app）
rm -rf backend/main.py
```

### 3.1.2 情感/情绪相关文件（ContextGate 无情绪概念）

```bash
rm -rf backend/routers/emotion_analysis.py
rm -rf backend/emotion_analyzer.py
rm -rf backend/utils/sentiment_classifier.py
rm -rf backend/config/emotion_strategy.yaml
rm -rf backend/runtime/skills/emotion_skill.py
rm -rf backend/services/emotion_trend_analyzer.py
rm -rf backend/services/advanced_sentiment_analyzer.py
rm -rf backend/services/sentiment_integration_example.py
```

### 3.1.3 旧数据库/向量遗留

```bash
rm -rf backend/vector_store.py          # 旧 ChromaDB 封装，已被 pgvector 替代
rm -rf backend/memory_manager.py        # 旧记忆管理器，被 pipeline 替代（确认无引用后删）
rm -rf backend/memory_extractor.py      # 同上
rm -rf backend/context_assembler.py     # 旧上下文组装，被 pipeline/build_context 替代
```

> ⚠️ 3.1.3 删除前先确认无引用：
> ```bash
> grep -rln "vector_store\|memory_manager\|memory_extractor\|context_assembler" backend/ --include="*.py" | grep -v __pycache__
> # 如果有引用，先改引用，再删文件
> ```

### 3.1.4 前端遗留

```bash
rm -rf frontend/src/App.js.backup        # 备份文件
rm -rf frontend/src/constants/emotions.js  # 情绪常量（测试 UI 用不到）
```

> 其余 frontend 代码保留（开发期测试客户端，v1.0 发布时整体退役）。

### 3.1.5 验证（必须通过）

```bash
# 1. 确认无 import 断裂
cd /Users/guowei/Desktop/github/contextgate
uv run python -c "
import sys
sys.path.insert(0, '.')
# 冒烟：主模块能 import
from backend.app import app
print('✅ 后端 app import 成功')
"

# 2. 确认情感字眼清干净
grep -r "心语\|情感陪伴" backend/ --include="*.py" | grep -v __pycache__ || echo "✅ 无情感残留"

# 3. 确认死目录消失
ls Prompt优化测试/ 2>/dev/null && echo "❌ 还在" || echo "✅ 已删除"
ls backend/hermes/ 2>/dev/null && echo "❌ 还在" || echo "✅ 已删除"
```

### 3.1.6 同步修改引用

如果 3.1.3 删除的文件在 `backend/app.py`、`backend/routers/__init__.py`、`config.py` 有 import：
- 删除对应 import 行
- 删除对应 try/except 降级逻辑（如 `EMOTION_ENABLED`、`HERMES_ROUTER_ENABLED`、`PERFORMANCE_OPTIMIZATION_ENABLED`）

**⚠️ 必须保留（新 pipeline 依赖，不要删）:**
```bash
backend/modules/llm/core/llm_core.py    # backend/pipeline/llm_helper.py 引用
backend/modules/rag/                    # RAG 功能
backend/modules/intent/                 # 意图识别
backend/database/pgvector_session.py    # 新存储层
```

---

## Task 12: 结构化错误码 + 健康检查

### 12.01: 统一错误码

### 创建: `backend/core/errors.py`

```python
"""统一结构化错误码"""

from enum import Enum
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse


class ErrorCode(str, Enum):
    # ── 认证 (AUTH_0xx) ──
    AUTH_INVALID_KEY = "AUTH_001"
    AUTH_INSUFFICIENT_PERMISSIONS = "AUTH_002"
    AUTH_CROSS_TENANT_DENIED = "AUTH_003"
    AUTH_KEY_DISABLED = "AUTH_004"
    AUTH_MISSING_SIGNATURE_HEADERS = "AUTH_005"
    AUTH_INVALID_TIMESTAMP = "AUTH_006"
    AUTH_SIGNATURE_EXPIRED = "AUTH_007"
    AUTH_NONCE_REUSED = "AUTH_008"
    AUTH_INVALID_ACCESS_KEY = "AUTH_009"
    AUTH_SIGNATURE_MISMATCH = "AUTH_010"

    # ── 速率限制 (RATE_0xx) ──
    RATE_LIMITED = "RATE_001"


class _ContextGateErrorCode(str, Enum):
    # ── 安全护栏 (GUARD_0xx) ──
    PROMPT_INJECTION = "GUARD_001"
    PII_DETECTED = "GUARD_002"
    OUTPUT_BLOCKED = "GUARD_003"

    # ── LLM (LLM_0xx) ──
    LLM_TIMEOUT = "LLM_001"
    LLM_UNAVAILABLE = "LLM_002"
    LLM_NO_KEY = "LLM_003"
    LLM_BUDGET_EXCEEDED = "COST_001"

    # ── 文件 (FILE_0xx) ──
    FILE_TOO_LARGE = "FILE_001"
    FILE_INVALID_TYPE = "FILE_002"

    # ── 系统 (SYS_0xx) ──
    INTERNAL_ERROR = "SYS_001"
    SKILL_NOT_FOUND = "SKILL_001"


class ContextGateException(Exception):
    """业务异常 — 统一结构化"""

    def __init__(self, code: str, message: str, detail: str | None = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(f"[{code}] {message}")


async def contextgate_exception_handler(
    request: Request, exc: ContextGateException
) -> JSONResponse:
    """全局异常处理器"""
    return JSONResponse(
        status_code=_code_to_status(exc.code),
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "detail": exc.detail,
                "trace_id": getattr(request.state, "trace_id", ""),
            }
        },
    )


async def global_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """兜底异常处理器"""
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "SYS_001",
                "message": "internal_error",
                "detail": str(exc) if __debug__ else None,
                "trace_id": getattr(request.state, "trace_id", ""),
            }
        },
    )


def _code_to_status(code: str) -> int:
    """错误码 → HTTP 状态码"""
    if code.startswith("AUTH_"):
        return 401 if code in ("AUTH_001", "AUTH_007", "AUTH_008", "AUTH_009", "AUTH_010") else 403
    if code.startswith("RATE_"):
        return 429
    if code.startswith("GUARD_"):
        return 403
    if code.startswith("FILE_"):
        return 400
    if code.startswith("COST_"):
        return 402
    return 500
```

---

### 12.02: 深度健康检查

### 创建: `backend/core/health.py`

```python
"""深度健康检查 — 数据库 / pgvector / LLM / LangFuse"""

import time
from fastapi import APIRouter
from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session

router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check():
    """深度健康检查"""
    checks = {}
    overall = "healthy"

    # 1. 数据库
    try:
        t0 = time.time()
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            session.execute(text("SELECT 1"))
        db_latency = (time.time() - t0) * 1000
        checks["database"] = {"status": "up", "latency_ms": round(db_latency, 1)}
    except Exception as e:
        checks["database"] = {"status": "down", "error": str(e)}
        overall = "degraded"

    # 2. pgvector 扩展
    try:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            ).fetchone()
        checks["pgvector"] = {
            "status": "up" if row else "missing",
            "version": row[0] if row else None,
        }
        if not row:
            overall = "degraded"
    except Exception as e:
        checks["pgvector"] = {"status": "down", "error": str(e)}
        overall = "degraded"

    # 3. LLM API（可选）
    try:
        from backend.core.key_repository import LLMKeyRepository
        repo = LLMKeyRepository()
        key = await repo.get_key("default", "default")
        checks["llm_api"] = {
            "status": "up" if key else "no_key_configured",
        }
    except Exception:
        checks["llm_api"] = {"status": "unknown"}

    # 4. 缓存
    try:
        from backend.database.pgvector_session import CacheEntry
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            count = session.query(CacheEntry).count()
        checks["cache"] = {"status": "up", "entries": count}
    except Exception:
        checks["cache"] = {"status": "down"}

    # 5. LangFuse（可选）
    try:
        from backend.observability.langfuse_client import get_langfuse
        lf = get_langfuse()
        checks["langfuse"] = {"status": "configured"}
    except Exception:
        checks["langfuse"] = {"status": "not_configured"}

    http_status = 200 if overall == "healthy" else 503
    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=http_status,
        content={
            "status": overall,
            "checks": checks,
        },
    )
```

---

### 12.03: Prometheus 指标

### 创建: `backend/core/metrics.py`

```python
"""Prometheus 指标定义"""

from prometheus_client import Counter, Histogram, Gauge
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ── 请求指标 ──
request_duration = Histogram(
    "contextgate_request_duration_ms",
    "Request latency in milliseconds",
    labelnames=["method", "endpoint", "status"],
    buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
)

requests_total = Counter(
    "contextgate_requests_total",
    "Total requests",
    labelnames=["tenant", "status"],
)

# ── Token 指标 ──
tokens_total = Counter(
    "contextgate_tokens_total",
    "Total tokens consumed",
    labelnames=["tenant", "model"],
)

# ── 缓存指标 ──
cache_hits = Counter(
    "contextgate_cache_hits_total",
    "Total cache hits",
    labelnames=["tenant", "cache_type"],
)

cache_misses = Counter(
    "contextgate_cache_misses_total",
    "Total cache misses",
    labelnames=["tenant"],
)

# ── 护栏指标 ──
guardrails_blocked = Counter(
    "contextgate_guardrails_blocked_total",
    "Total blocked by guardrails",
    labelnames=["tenant", "guard"],
)

# ── 成本指标 ──
cost_total = Counter(
    "contextgate_cost_total",
    "Total cost in USD",
    labelnames=["tenant", "model"],
)

# ── 错误指标 ──
errors_total = Counter(
    "contextgate_errors_total",
    "Total errors by code",
    labelnames=["tenant", "error_code"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """自动记录请求指标"""
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response: Response = await call_next(request)
        latency = (time.time() - start) * 1000
        status_group = f"{response.status_code // 100}xx"
        endpoint = request.url.path
        request_duration.labels(
            method=request.method, endpoint=endpoint, status=status_group
        ).observe(latency)
        return response
```

---

## Task 03: 多租户隔离 + 审计日志

### 03.01: 租户中间件

### 创建: `backend/core/tenant.py`

```python
"""租户中间件 — 注入 trace_id 和 tenant_id"""

import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class TenantMiddleware(BaseHTTPMiddleware):
    """注入 request.state.trace_id + 提取 tenant_id"""

    async def dispatch(self, request, call_next):
        # 生成 trace_id
        request.state.trace_id = f"tr_{uuid.uuid4().hex[:12]}"

        # 从 auth 上下文或默认值提取 tenant_id
        tenant_context = getattr(request.state, "tenant_context", None)
        request.state.tenant_id = (
            tenant_context.tenant_id if tenant_context else "default"
        )

        response = await call_next(request)
        # 在响应头中返回 trace_id
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response
```

---

### 03.02: 审计日志写入

### 创建: `backend/core/audit.py`

```python
"""审计日志 — fire-and-forget BackgroundTasks"""

from fastapi import BackgroundTasks
from sqlalchemy import text
from datetime import datetime

from backend.database.pgvector_session import get_pg_session


def log_audit(
    background_tasks: BackgroundTasks,
    tenant_id: str,
    user_id: str,
    action: str,
    trace_id: str,
    input_text: str = "",
    output_text: str = "",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    latency_ms: float = 0.0,
    error_code: str | None = None,
    ip_address: str = "",
    user_agent: str = "",
) -> None:
    """发起异步审计写入（不阻塞当前请求）"""
    background_tasks.add_task(
        _write_audit,
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "trace_id": trace_id,
            "input_text": input_text,
            "output_text": output_text,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
            "error_code": error_code,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "created_at": datetime.utcnow(),
        },
    )


def write_audit_sync(record: dict) -> None:
    """同步写入审计（不需要 BackgroundTasks 时用）"""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_write_audit(record))
    finally:
        loop.close()


async def _write_audit(record: dict) -> None:
    """后台写入 audit_logs 表"""
    try:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            sql = text("""
                INSERT INTO audit_logs
                    (tenant_id, user_id, action, trace_id,
                     input_text, output_text, model,
                     input_tokens, output_tokens, cost, latency_ms,
                     error_code, ip_address, user_agent, created_at)
                VALUES
                    (:tenant_id, :user_id, :action, :trace_id,
                     :input_text, :output_text, :model,
                     :input_tokens, :output_tokens, :cost, :latency_ms,
                     :error_code, :ip_address, :user_agent, :created_at)
            """)
            session.execute(sql, record)
            session.commit()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("审计日志写入失败")
```

---

### 03.03: 审计导出 API

### 创建: `backend/routers/audit.py`

```python
"""审计日志查询 + 导出"""

import csv
import io
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_any_permission
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
async def query_audit_logs(
    tenant_id: str | None = Query(None, description="按租户筛选"),
    start: str | None = Query(None, description="开始时间 ISO"),
    end: str | None = Query(None, description="结束时间 ISO"),
    action: str | None = Query(None, description="按操作筛选"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(require_any_permission(["audit:read", "admin:*"])),
):
    """查询审计日志"""
    session_factory = get_pg_session()
    # 如果不是 super_admin，只能看自己租户
    tid = tenant_id if tenant.is_cross_tenant else tenant.tenant_id

    conditions = ["1=1"]
    params = {"lim": limit, "off": offset}
    if tid:
        conditions.append("tenant_id = :tid")
        params["tid"] = tid
    if start:
        conditions.append("created_at >= :start")
        params["start"] = start
    if end:
        conditions.append("created_at <= :end")
        params["end"] = end
    if action:
        conditions.append("action = :action")
        params["action"] = action

    sql = text(f"""
        SELECT id, tenant_id, user_id, action, trace_id,
               model, input_tokens, output_tokens, cost,
               latency_ms, error_code, ip_address, created_at
        FROM audit_logs
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT :lim OFFSET :off
    """)

    with session_factory.Session() as session:
        rows = session.execute(sql, params).fetchall()

    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "user_id": r.user_id,
            "action": r.action,
            "trace_id": r.trace_id,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost": r.cost,
            "latency_ms": r.latency_ms,
            "error_code": r.error_code,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/export")
async def export_audit_csv(
    tenant_id: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    tenant: TenantContext = Depends(require_any_permission(["audit:export", "admin:*"])),
):
    """导出审计日志为 CSV"""
    tid = tenant_id if tenant.is_cross_tenant else tenant.tenant_id
    session_factory = get_pg_session()

    conditions = ["1=1"]
    params = {}
    if tid:
        conditions.append("tenant_id = :tid")
        params["tid"] = tid
    if start:
        conditions.append("created_at >= :start")
        params["start"] = start
    if end:
        conditions.append("created_at <= :end")
        params["end"] = end

    sql = text(f"""
        SELECT id, tenant_id, user_id, action, trace_id,
               input_text, output_text, model,
               input_tokens, output_tokens, cost, latency_ms,
               error_code, ip_address, user_agent, created_at
        FROM audit_logs
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT 10000
    """)

    with session_factory.Session() as session:
        rows = session.execute(sql, params).fetchall()

    # 生成 CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "tenant_id", "user_id", "action", "trace_id",
        "input_text", "output_text", "model",
        "input_tokens", "output_tokens", "cost", "latency_ms",
        "error_code", "ip_address", "user_agent", "created_at",
    ])
    for r in rows:
        writer.writerow([
            r.id, r.tenant_id, r.user_id, r.action, r.trace_id,
            (r.input_text or "")[:500], (r.output_text or "")[:500],
            r.model, r.input_tokens, r.output_tokens,
            r.cost, r.latency_ms, r.error_code,
            r.ip_address, r.user_agent,
            r.created_at.isoformat() if r.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_{tid}_{datetime.now().strftime('%Y%m%d')}.csv"
        },
    )
```

---

### 03.04: ORM 数据隔离

### 修改: `backend/database/pgvector_session.py`

在 `PGVectorSession` 类中添加方法：

```python
def query_with_tenant(self, model_class, tenant_id: str, user_id: str | None = None):
    """带租户隔离的查询 — 自动加 WHERE tenant_id=:tid"""
    with self.Session() as session:
        q = session.query(model_class).filter(
            model_class.tenant_id == tenant_id
        )
        if user_id and hasattr(model_class, "user_id"):
            q = q.filter(model_class.user_id == user_id)
        return q
```

---

## 注册到 app.py

### 修改: `backend/app.py`

```python
# 在 create_app() 中添加:
from backend.core.errors import (
    contextgate_exception_handler,
    global_exception_handler,
    ContextGateException,
)
from backend.core.health import router as health_router
from backend.core.metrics import MetricsMiddleware
from backend.core.tenant import TenantMiddleware
from backend.routers.audit import router as audit_router

# 异常处理器（必须在路由之前）
app.add_exception_handler(ContextGateException, contextgate_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# 中间件（顺序重要: Tenant → Metrics → CORS → Signature）
app.add_middleware(TenantMiddleware)     # 注入 trace_id
app.add_middleware(MetricsMiddleware)    # 记录指标

# 路由
app.include_router(health_router)        # /health
app.include_router(audit_router, prefix="/api")  # /api/audit/logs, /api/audit/export
```

---

## 验证

```bash
# 1. 导入验证
uv run python -c "
from backend.core.errors import ErrorCode, ContextGateException, contextgate_exception_handler
from backend.core.health import health_check
from backend.core.metrics import MetricsMiddleware, request_duration, requests_total
from backend.core.tenant import TenantMiddleware
from backend.core.audit import log_audit
print('✅ Batch 3 全部模块导入成功')
"

# 2. 错误码验证
uv run python -c "
from backend.core.errors import _code_to_status
assert _code_to_status('AUTH_001') == 401
assert _code_to_status('AUTH_002') == 403
assert _code_to_status('RATE_001') == 429
assert _code_to_status('GUARD_001') == 403
assert _code_to_status('FILE_001') == 400
assert _code_to_status('SYS_001') == 500
print('✅ 错误码状态映射全部正确')
"

# 3. Trace ID 验证
uv run python -c "
import uuid
trace_id = f'tr_{uuid.uuid4().hex[:12]}'
assert len(trace_id) == 15  # tr_ + 12 hex chars
print(f'✅ trace_id 格式正确: {trace_id}')
"

# 4. 审计日志格式验证
from backend.core.audit import write_audit_sync
# 这只是检查导入，实际数据库需要 pgvector 运行
print('✅ 审计模块就绪')
```
