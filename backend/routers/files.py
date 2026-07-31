"""文件上传接口 — 安全加固版"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.core.file_sanitizer import (
    MAX_FILE_SIZE,
    UPLOAD_DIR,
    sanitize_filename,
    validate_file,
)
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """上传文件（安全加固）"""
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

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name, _ext = sanitize_filename(file.filename or "upload")
    file_path = UPLOAD_DIR / safe_name

    with open(file_path, "wb") as f:
        f.write(content)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        session.execute(
            text(
                """
                INSERT INTO cache_entries
                    (cache_key, cache_type, tenant_id, value, ttl_seconds, expires_at)
                VALUES
                    (:key, 'file', :tid, :path, 86400, now() + interval '24 hours')
                """
            ),
            {
                "key": f"file:{safe_name}",
                "tid": tenant.tenant_id,
                "path": str(file_path),
            },
        )
        session.commit()

    return {
        "file_id": safe_name,
        "original_name": file.filename,
        "size": len(content),
        "content_type": content_type,
    }


@router.get("/{file_id}")
async def get_file(file_id: str):
    """获取上传文件"""
    safe_name = os.path.basename(file_id)
    file_path = UPLOAD_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="file_not_found")
    return FileResponse(str(file_path))
