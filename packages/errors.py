"""统一结构化错误码"""

from __future__ import annotations

import logging
import os
from enum import StrEnum

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


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

    # ── 席位/订阅 (SEAT_0xx) ──
    SEAT_LIMIT = "SEAT_001"

    # ── 安全护栏 (GUARD_0xx) ──
    PROMPT_INJECTION = "GUARD_001"
    PII_DETECTED = "GUARD_002"
    OUTPUT_BLOCKED = "GUARD_003"

    # ── LLM (LLM_0xx) / 成本 ──
    LLM_TIMEOUT = "LLM_001"
    LLM_UNAVAILABLE = "LLM_002"
    LLM_NO_KEY = "LLM_003"
    LLM_KEY_MISSING = "LLM_KEY_001"
    LLM_MODEL_NOT_ALLOWED = "LLM_KEY_002"
    LLM_KEY_DUPLICATE_SERIES = "LLM_KEY_003"
    LLM_MODEL_REQUIRED = "LLM_KEY_004"
    LLM_BUDGET_EXCEEDED = "COST_001"

    # ── 计费 (BILLING_0xx) ──
    INSUFFICIENT_BALANCE = "BILLING_003"

    # ── 条款 (TERMS_0xx) ──
    TERMS_NOT_ACCEPTED = "TERMS_001"
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
    CAP_CONTRACT_INVALID = "CAP_006"

    # ── 请求校验 (REQ_0xx) ──
    REQ_INVALID = "REQ_001"

    # ── 系统 (SYS_0xx) ──
    INTERNAL_ERROR = "SYS_001"
    SKILL_NOT_FOUND = "SKILL_001"

    # ── 工作流 (WF_0xx / RUN_0xx) ──
    WF_CREATE_FORBIDDEN = "WF_001"
    WF_EDIT_FORBIDDEN = "WF_002"
    WF_IR_INVALID = "WF_010"
    WF_IR_CAPABILITY_MISSING = "WF_011"
    WF_IR_UNKNOWN_CAPABILITY = "WF_012"
    WF_NOT_DRAFT = "WF_020"
    WF_REVISION_CONFLICT = "WF_021"
    WF_ALREADY_PUBLISHED = "WF_030"
    WF_FORK_REQUIRES_PUBLISHED = "WF_040"
    WF_DELETE_DRAFT_ONLY = "WF_050"
    WF_NOT_FOUND = "WF_404"
    RUN_PUBLISH_FIRST = "RUN_001"
    RUN_PRIMARY_ORG_REQUIRED = "RUN_002"
    RUN_CAS_CONFLICT = "RUN_003"
    RUN_ACTING_USER_NOT_FOUND = "RUN_010"
    RUN_NOT_FOUND = "RUN_404"
    RUN_INJECTION = "RUN_INJECT"
    RUN_CONCURRENCY_LIMIT = "RUN_CONCURRENCY_LIMIT"
    RUN_ZOMBIE = "RUN_ZOMBIE"
    RUN_500 = "RUN_500"


class NexusAIException(Exception):
    """业务异常 — 统一结构化"""

    def __init__(
        self,
        code: str,
        message: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.code = code
        self.message = message
        self.detail = detail
        self.headers = dict(headers or {})
        super().__init__(f"[{code}] {message}")


async def nexusai_exception_handler(
    request: Request, exc: NexusAIException
) -> JSONResponse:
    """全局业务异常处理器"""
    if exc.code.startswith("AUTH_"):
        _audit_auth_failure(request, exc.code, exc.message)
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
        headers=dict(exc.headers or {}),
    )


def _expose_internal_detail() -> bool:
    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    if env == "production":
        return False
    return (os.getenv("DEBUG") or "").strip().lower() in ("1", "true", "yes")


def internal_error_payload(request: Request, exc: Exception | None = None) -> dict:
    """Task 59 S2 — 500 仅回 code + trace_id（详情进日志）。"""
    if exc is not None:
        logger.exception("internal_error", exc_info=exc)
    trace_id = str(getattr(request.state, "trace_id", "") or "")
    payload: dict = {
        "code": "INTERNAL",
        "message": "internal_error",
        "trace_id": trace_id,
    }
    if exc is not None and _expose_internal_detail():
        payload["detail"] = str(exc)
    return payload


def raise_internal_error(request: Request, exc: Exception) -> None:
    """记录异常并抛出不含内部细节的 HTTP 500。"""
    from fastapi import HTTPException

    raise HTTPException(status_code=500, detail=internal_error_payload(request, exc))


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理器；生产不回堆栈 / 内部路径。"""
    return JSONResponse(
        status_code=500,
        content=internal_error_payload(request, exc),
    )


def _audit_auth_failure(request: Request, code: str, message: str) -> None:
    try:
        from backend.core.audit import write_audit_sync

        tenant = getattr(request.state, "tenant_context", None)
        write_audit_sync(
            {
                "tenant_id": getattr(tenant, "tenant_id", None) or "unknown",
                "user_id": getattr(tenant, "user_id", None) or "anonymous",
                "action": "auth_denied",
                "trace_id": str(getattr(request.state, "trace_id", "") or ""),
                "input_text": "",
                "output_text": "",
                "error_code": code,
                "ip_address": request.client.host if request.client else "",
                "user_agent": request.headers.get("User-Agent", ""),
            }
        )
    except Exception:
        pass


async def http_exception_audit_handler(request: Request, exc: Exception) -> JSONResponse:
    status = int(getattr(exc, "status_code", 500) or 500)
    if status in (401, 403):
        _audit_auth_failure(request, f"HTTP_{status}", str(getattr(exc, "detail", "")))
    if status >= 500:
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict) and detail.get("code") == "INTERNAL":
            content = detail
        else:
            content = internal_error_payload(
                request,
                detail if isinstance(detail, Exception) else None,
            )
            if isinstance(detail, str) and _expose_internal_detail():
                content["detail"] = detail
        return JSONResponse(
            status_code=status,
            content=content,
            headers=dict(getattr(exc, "headers", None) or {}),
        )
    return JSONResponse(
        status_code=status,
        content={"detail": getattr(exc, "detail", "error")},
        headers=dict(getattr(exc, "headers", None) or {}),
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
            "CAP_006": 422,
        }.get(code, 400)
    if code.startswith("REQ_"):
        return 400
    if code.startswith("LLM_KEY_"):
        return 400
    return 500
