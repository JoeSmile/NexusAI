"""统一结构化错误码"""

from __future__ import annotations

from enum import StrEnum

from starlette.requests import Request
from starlette.responses import JSONResponse


class ErrorCode(StrEnum):
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

    # ── 安全护栏 (GUARD_0xx) ──
    PROMPT_INJECTION = "GUARD_001"
    PII_DETECTED = "GUARD_002"
    OUTPUT_BLOCKED = "GUARD_003"

    # ── LLM (LLM_0xx) / 成本 ──
    LLM_TIMEOUT = "LLM_001"
    LLM_UNAVAILABLE = "LLM_002"
    LLM_NO_KEY = "LLM_003"
    LLM_BUDGET_EXCEEDED = "COST_001"

    # ── 文件 (FILE_0xx) ──
    FILE_TOO_LARGE = "FILE_001"
    FILE_INVALID_TYPE = "FILE_002"
    FILE_NOT_FOUND = "FILE_003"

    # ── RAG / 多模态 (RAG_0xx) ──
    RAG_DEP_MISSING = "RAG_001"
    RAG_EMPTY_EXTRACT = "RAG_002"

    # ── 缓存 (CACHE_0xx) ──
    CACHE_UNAVAILABLE = "CACHE_001"

    # ── 能力层 (CAP_0xx) ──
    CAP_NOT_FOUND = "CAP_001"
    CAP_DISABLED = "CAP_002"
    CAP_UPSTREAM_ERROR = "CAP_003"
    CAP_GOVERNANCE_REQUIRED = "CAP_004"
    CAP_QUOTA_EXCEEDED = "CAP_005"

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
    """全局业务异常处理器"""
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


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理器"""
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "internal_error",
                "detail": str(exc) if __debug__ else None,
                "trace_id": getattr(request.state, "trace_id", ""),
            }
        },
    )


def _code_to_status(code: str) -> int:
    """错误码 → HTTP 状态码"""
    if code.startswith("AUTH_"):
        return (
            401
            if code
            in (
                "AUTH_001",
                "AUTH_007",
                "AUTH_008",
                "AUTH_009",
                "AUTH_010",
            )
            else 403
        )
    if code.startswith("RATE_"):
        return 429
    if code.startswith("GUARD_"):
        return 403
    if code.startswith("FILE_"):
        return 400
    if code.startswith("RAG_"):
        return 501 if code == "RAG_001" else 422
    if code.startswith("CACHE_"):
        return 503
    if code.startswith("COST_"):
        return 402
    if code.startswith("CAP_"):
        return {
            "CAP_001": 404,
            "CAP_002": 403,
            "CAP_003": 502,
            "CAP_004": 403,
            "CAP_005": 429,
        }.get(code, 400)
    return 500
