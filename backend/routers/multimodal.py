"""Multimodal chat — image upload + vision model (Task 58)."""

from __future__ import annotations

import time
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

from backend.core.audit import log_audit
from backend.core.audit_context import bind_audit_lineage
from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.billing.context import bind_billing_context
from backend.core.errors import ErrorCode, NexusAIException
from backend.core.file_sanitizer import sanitize_filename, validate_file
from backend.core.guardrails.image_guard import check_image_input
from backend.core.harness import LLMHarness
from backend.core.multimodal.vision import (
    build_vision_messages,
    image_to_data_uri,
    resolve_vision_credentials,
)
from backend.core.terms.service import enforce_terms_for_chat
from backend.models import MultimodalResponse

router = APIRouter(prefix="/multimodal", tags=["multimodal"])
_harness = LLMHarness()


async def require_multimodal_vision(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> TenantContext:
    if not tenant.has_permission("multimodal:vision"):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "multimodal_vision_denied"},
        )
    return tenant


@router.post("/chat", response_model=MultimodalResponse)
async def multimodal_chat(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    text: str = Form(""),
    model: str | None = Form(None),
    session_id: str = Form("default"),
    tenant: TenantContext = Depends(require_multimodal_vision),
):
    """上传图片 + 文本 → 视觉模型回复。"""
    enforce_terms_for_chat(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        credential_kind="company",
        ip_address=request.client.host if request.client else None,
    )

    content = await file.read()
    content_type = file.content_type or "application/octet-stream"
    valid, error_msg = validate_file(file.filename or "upload.jpg", content, content_type)
    if not valid:
        code = error_msg.split(":")[0] if ":" in error_msg else ErrorCode.FILE_INVALID_TYPE.value
        raise NexusAIException(code, error_msg)

    ok, guard_code, image_hash = check_image_input(
        content=content,
        filename=file.filename or "upload",
        content_type=content_type,
    )
    if not ok:
        raise NexusAIException(guard_code or ErrorCode.FILE_INVALID_TYPE.value, "image_rejected")

    trace_id = getattr(request.state, "trace_id", None) or f"tr_{uuid.uuid4().hex[:12]}"
    bind_audit_lineage(trace_id=trace_id)
    bind_billing_context(
        user_id=tenant.user_id,
        trace_id=trace_id,
        idempotency_suffix="vision",
        modality="image",
        image_hash=image_hash,
    )

    model_name, api_key, base_url, provider = await resolve_vision_credentials(
        tenant.tenant_id, model
    )
    data_uri = image_to_data_uri(content, content_type)
    messages = build_vision_messages(text, data_uri)

    start = time.time()
    result = await _harness.generate(
        model=model_name,
        messages=messages,
        tenant_id=tenant.tenant_id,
        api_key=api_key,
        base_url=base_url,
        provider=provider,
        max_tokens=1024,
    )
    latency_ms = (time.time() - start) * 1000

    if not result.success:
        log_audit(
            background_tasks,
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            action="multimodal_vision",
            trace_id=trace_id,
            input_text=(text or "")[:500],
            output_text=str(result.output or "")[:500],
            model=model_name,
            error_code=result.error,
            latency_ms=latency_ms,
            ip_address=request.client.host if request.client else "",
            modality="image",
            image_hash=image_hash,
        )
        raise NexusAIException(
            result.error or ErrorCode.LLM_UNAVAILABLE.value,
            str(result.output or "vision_request_failed"),
        )

    output = str(result.output or "")
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="multimodal_vision",
        trace_id=trace_id,
        input_text=(text or "")[:500],
        output_text=output[:2000],
        model=model_name,
        input_tokens=int(result.metadata.get("input_tokens", 0) or 0),
        output_tokens=int(result.metadata.get("output_tokens", 0) or 0),
        cost=float(result.metadata.get("cost", 0.0) or 0.0),
        latency_ms=latency_ms,
        ip_address=request.client.host if request.client else "",
        modality="image",
        image_hash=image_hash,
    )

    safe_name, _ = sanitize_filename(file.filename or "upload.jpg")

    return MultimodalResponse(
        response=output,
        session_id=session_id,
        context={
            "trace_id": trace_id,
            "model": model_name,
            "file_id": safe_name,
            "image_hash": image_hash,
            "modality": "image",
        },
    )
