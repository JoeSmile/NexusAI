"""文件上传 — 仅登录用户；下载仅本人。ACL TTL 默认 7 天（对齐会话附件）。"""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text

from packages.attachments.auto_describe import maybe_describe_on_upload
from packages.attachments.errors import ParseError
from packages.attachments.service import ingest_bytes
from packages.attachments.store import AttachmentForbidden, get_attachment_store
from packages.attachments.validate import ATTACHMENT_MAX_BYTES
from packages.audit import write_audit_sync
from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from packages.database.pgvector_session import get_pg_session
from packages.file_sanitizer import (
    MAX_FILE_SIZE,
    UPLOAD_DIR,
    sanitize_filename,
    validate_file,
)

router = APIRouter(prefix="/api/files", tags=["files"])

_FILE_ID_RE = re.compile(r"^[a-f0-9]{32}(\.[A-Za-z0-9]{1,8})?$")
# 与 Task 76 会话附件同一默认窗口；env ``FILE_ACL_TTL_SECONDS`` 可配
FILE_ACL_TTL_DEFAULT = 7 * 24 * 3600


def file_acl_ttl_seconds() -> int:
    raw = (os.getenv("FILE_ACL_TTL_SECONDS") or "").strip()
    if not raw:
        return FILE_ACL_TTL_DEFAULT
    try:
        n = int(raw)
    except ValueError:
        return FILE_ACL_TTL_DEFAULT
    return n if n > 0 else FILE_ACL_TTL_DEFAULT


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())[:80]
    return cleaned or "_"


def _file_cache_key(tenant_id: str, user_id: str, file_id: str) -> str:
    return f"file:{tenant_id}:{user_id}:{file_id}"


def _owned_path(tenant_id: str, user_id: str, file_id: str) -> Path:
    return UPLOAD_DIR / _safe_part(tenant_id) / _safe_part(user_id) / file_id


@router.post("")
async def upload_session_attachment(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """Chat 会话附件：解析进 attachment_blocks，不进知识库。"""
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(
            status_code=400,
            detail={"code": "FILE_SESSION", "message": "session_id_required"},
        )
    content = await file.read()
    filename = file.filename or "upload.bin"
    if len(content) > ATTACHMENT_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail={"code": "FILE_TOO_LARGE", "message": "file_exceeds_20mb"},
        )
    ttl = file_acl_ttl_seconds()
    expires = datetime.now(UTC) + timedelta(seconds=ttl)
    aid = uuid.uuid4().hex
    dest = _owned_path(tenant.tenant_id, tenant.user_id, aid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    try:
        result = ingest_bytes(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            session_id=sid,
            filename=filename,
            data=content,
            storage_path=str(dest),
            expired_at=expires,
            attachment_id=aid,
        )
    except ParseError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    store = get_attachment_store()
    row = store.get(
        tenant_id=tenant.tenant_id,
        session_id=sid,
        attachment_id=str(result.get("attachment_id") or aid),
    )
    media = str((row or {}).get("media_type") or "")
    describe_status = await maybe_describe_on_upload(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        session_id=sid,
        attachment_id=str(result.get("attachment_id") or aid),
        media_type=media,
    )
    result["size"] = len(content)
    result["describe_status"] = describe_status
    return result


@router.get("/{attachment_id}/blocks")
async def get_attachment_blocks(
    attachment_id: str,
    session_id: str,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """仅本 tenant + 本 session 可读块。"""
    store = get_attachment_store()
    try:
        row = store.get(
            tenant_id=tenant.tenant_id,
            session_id=(session_id or "").strip(),
            attachment_id=attachment_id,
        )
    except AttachmentForbidden as exc:
        write_audit_sync(
            {
                "tenant_id": tenant.tenant_id,
                "user_id": tenant.user_id,
                "action": "attachment_denied",
                "trace_id": attachment_id,
                "error_code": "AUTH_004",
                "model": "files",
                "input_text": exc.reason,
                "created_at": datetime.now(UTC),
            }
        )
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_004", "message": "attachment_forbidden"},
        ) from None
    if not row:
        raise HTTPException(status_code=404, detail="file_not_found")
    return {
        "attachment_id": row["id"],
        "status": row["status"],
        "name": row["name"],
        "blocks": row["blocks"],
    }


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """上传文件（登录用户；落点按租户+用户隔离）。"""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail={"code": "FILE_001", "message": "文件超过 10MB 限制"},
        )

    content_type = file.content_type or ""
    valid, error_msg = validate_file(file.filename or "", content, content_type)
    if not valid:
        code = error_msg.split(":")[0]
        raise HTTPException(status_code=400, detail={"code": code, "message": error_msg})

    file_id, _ext = sanitize_filename(file.filename or "upload")
    file_path = _owned_path(tenant.tenant_id, tenant.user_id, file_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    ttl = file_acl_ttl_seconds()
    expires = datetime.now(UTC) + timedelta(seconds=ttl)
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        session.execute(
            text(
                """
                INSERT INTO cache_entries
                    (cache_key, cache_type, tenant_id, value, ttl_seconds, expires_at)
                VALUES
                    (:key, 'file', :tid, :path, :ttl, :expires)
                """
            ),
            {
                "key": _file_cache_key(tenant.tenant_id, tenant.user_id, file_id),
                "tid": tenant.tenant_id,
                "path": str(file_path),
                "ttl": ttl,
                "expires": expires,
            },
        )
        session.commit()

    return {
        "file_id": file_id,
        "original_name": file.filename,
        "size": len(content),
        "content_type": content_type,
    }


@router.get("/{file_id}")
async def get_file(
    file_id: str,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """仅上传者可下载；过期 ACL（默认 7 天）与未登录 / 他人 / 跨租户一律 401 或 404。"""
    safe_name = os.path.basename(file_id)
    if not _FILE_ID_RE.match(safe_name):
        raise HTTPException(status_code=404, detail="file_not_found")

    key = _file_cache_key(tenant.tenant_id, tenant.user_id, safe_name)
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = session.execute(
            text(
                """
                SELECT value FROM cache_entries
                WHERE cache_key = :key AND tenant_id = :tid
                  AND expires_at > now()
                """
            ),
            {"key": key, "tid": tenant.tenant_id},
        ).first()

    if not row:
        raise HTTPException(status_code=404, detail="file_not_found")

    mapping = getattr(row, "_mapping", row)
    stored = Path(str(mapping["value"]))
    expected = _owned_path(tenant.tenant_id, tenant.user_id, safe_name).resolve()
    try:
        stored_resolved = stored.resolve()
    except OSError:
        raise HTTPException(status_code=404, detail="file_not_found") from None
    if stored_resolved != expected or not stored_resolved.is_file():
        raise HTTPException(status_code=404, detail="file_not_found")
    return FileResponse(str(stored_resolved))
