# Task 12: 健康检查 + SLA 指标 + 结构化错误码

> 所有异常统一 `{"error": {"code", "message", "detail", "trace_id"}}`

## Subtask 12.01: 结构化错误码

**文件:** `backend/core/errors.py`
```python
class ErrorCode(str, Enum):
    AUTH_INVALID_KEY = "AUTH_001"
    AUTH_INSUFFICIENT_PERMISSIONS = "AUTH_002"
    AUTH_CROSS_TENANT_DENIED = "AUTH_003"
    RATE_LIMITED = "RATE_001"
    PROMPT_INJECTION = "GUARD_001"
    PII_DETECTED = "GUARD_002"
    OUTPUT_BLOCKED = "GUARD_003"
    LLM_TIMEOUT = "LLM_001"
    LLM_UNAVAILABLE = "LLM_003"
    FILE_TOO_LARGE = "FILE_001"
    FILE_INVALID_TYPE = "FILE_002"
    INTERNAL_ERROR = "SYS_001"
```

## Subtask 12.02: 深度健康检查

**文件:** `backend/core/health.py`
```python
GET /health → {
    "status": "healthy",
    "checks": {
        "database": {"status": "up", "latency_ms": 2},
        "pgvector": {"status": "up"},
        "llm_api": {"status": "up"},
        "cache": {"status": "up"},
        "langfuse": {"status": "up"},
    }
}
```

## Subtask 12.03: Prometheus 指标

**文件:** `backend/core/metrics.py`
```
contextgate_request_duration_ms{quantile="0.5", tenant="acme"}
contextgate_requests_total{tenant="acme", status="success"}
contextgate_tokens_total{tenant="acme", model="deepseek-v4"}
contextgate_cache_hit_ratio{tenant="acme", cache_type="template"}
contextgate_guardrails_blocked_total{tenant="acme", guard="input"}
contextgate_cost_total{tenant="acme", model="deepseek-v4"}
contextgate_errors_total{tenant="acme", error_code="LLM_TIMEOUT"}
```

**修改:** `backend/app.py` — 挂 `/metrics` 端点

## 验证

```bash
curl http://localhost:8000/health   # → 所有 checks up
curl http://localhost:8000/metrics  # → Prometheus 格式
```
