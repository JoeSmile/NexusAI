"""Task 45 — offerings catalog + content style / hotspot / script HTTP."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.content_ops.hotspot import dig_hotspots
from backend.core.content_ops.offerings import get_offering, list_offerings
from backend.core.content_ops.script_gen import generate_script
from backend.core.content_ops.style import (
    DEFAULT_CREATOR_ID,
    delete_content_style,
    get_org_content_profile,
    list_content_styles,
    resolve_style_for_generate,
    set_org_content_profile,
    upsert_content_style,
)
from backend.database.pgvector_session import ContentArtifact, get_pg_session

router = APIRouter(tags=["content-ops"])


class StyleBody(BaseModel):
    display_name: str | None = None
    persona: str | None = None
    addressing: list[str] | None = None
    catchphrases: list[str] | None = None
    avg_sentence_len: str | None = None
    structure_habits: list[str] | None = None
    taboos: list[str] | None = None
    sample_openers: list[str] | None = None
    source_doc_ids: list[str] | None = None


class OrgProfileBody(BaseModel):
    name: str | None = None
    industry: str | None = None
    product_focus: str | None = None
    target_audience: str | None = None
    target_region: str | None = None
    extra: dict[str, Any] | None = None


class HotspotBody(BaseModel):
    adapter: str = "topic_agent"
    categories: list[str] | None = None
    keywords: str | None = None
    paste_text: str | None = None
    save: bool = True


class ScriptBody(BaseModel):
    creator_id: str = DEFAULT_CREATOR_ID
    hotspots: list[dict[str, Any]] = Field(default_factory=list)
    duration_sec: int = 60
    platform: str = "短视频"
    extra_instruction: str = ""
    student_names: list[str] | None = None
    save: bool = True


class StyleExtractBody(BaseModel):
    creator_id: str = DEFAULT_CREATOR_ID
    text: str = Field(..., min_length=1)
    save: bool = True


@router.get("/api/offerings")
async def api_list_offerings(
    dept: str | None = Query(default=None),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        items = list_offerings(session, tenant_id=tenant.tenant_id, dept=dept)
        session.commit()
    return {"items": items, "count": len(items)}


@router.get("/api/offerings/{offering_id}")
async def api_get_offering(
    offering_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        item = get_offering(session, offering_id)
        session.commit()
    if item is None:
        raise HTTPException(status_code=404, detail="offering_not_found")
    if item["tenant_id"] not in ("*", tenant.tenant_id) and not tenant.is_cross_tenant:
        raise HTTPException(status_code=404, detail="offering_not_found")
    return item


@router.get("/api/content/styles")
async def api_list_styles(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        items = list_content_styles(session, tenant.tenant_id)
    return {"items": items, "default_creator_id": DEFAULT_CREATOR_ID}


@router.put("/api/content/styles/{creator_id}")
async def api_upsert_style(
    creator_id: str,
    body: StyleBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    sf = get_pg_session()
    with sf.Session() as session:
        saved = upsert_content_style(session, tenant.tenant_id, creator_id, data)
        session.commit()
    return {"style": saved}


@router.post("/api/content/styles/{creator_id}/extract")
async def api_extract_style(
    creator_id: str,
    body: StyleExtractBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    from backend.core.content_ops.style_extract import extract_style_from_text

    extracted = await extract_style_from_text(
        tenant_id=tenant.tenant_id,
        creator_id=creator_id,
        text=body.text,
    )
    if body.save:
        sf = get_pg_session()
        with sf.Session() as session:
            extracted = upsert_content_style(
                session, tenant.tenant_id, creator_id, extracted
            )
            session.commit()
    return {"style": extracted}


@router.post("/api/content/styles/{creator_id}/upload")
async def api_upload_style_speech(
    creator_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload speech transcript for THIS creator only; always re-extract + overwrite.

    Not RAG / company knowledge ingest — separate button, separate path.
    """
    from backend.core.content_ops.file_text import (
        allowed_style_suffix,
        extract_text_from_bytes,
    )
    from backend.core.content_ops.style_extract import extract_style_from_text

    fname = file.filename or "upload.bin"
    if not allowed_style_suffix(fname):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "STYLE_FILE_TYPE",
                "message": "style_upload_txt_pdf_docx_only",
            },
        )
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=400,
            detail={"code": "STYLE_FILE_EMPTY", "message": "empty_file"},
        )
    try:
        text = extract_text_from_bytes(filename=fname, data=data)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "STYLE_PARSE_FAIL", "message": str(e)},
        ) from e
    if len(text.strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail={"code": "STYLE_TEXT_SHORT", "message": "extracted_text_too_short"},
        )
    extracted = await extract_style_from_text(
        tenant_id=tenant.tenant_id,
        creator_id=creator_id,
        text=text,
    )
    extracted["source_doc_ids"] = [fname]
    sf = get_pg_session()
    with sf.Session() as session:
        saved = upsert_content_style(session, tenant.tenant_id, creator_id, extracted)
        session.commit()
    return {
        "style": saved,
        "chars": len(text),
        "filename": fname,
        "reparsed": True,
    }


@router.delete("/api/content/styles/{creator_id}")
async def api_delete_style(
    creator_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        ok = delete_content_style(session, tenant.tenant_id, creator_id)
        session.commit()
    if not ok:
        raise HTTPException(status_code=404, detail="style_not_found")
    return {"deleted": True, "creator_id": creator_id}


@router.get("/api/content/org-profile")
async def api_get_org_profile(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        profile = get_org_content_profile(session, tenant.tenant_id)
    return {"profile": profile}


@router.put("/api/content/org-profile")
async def api_put_org_profile(
    body: OrgProfileBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if "extra" in data and isinstance(data["extra"], dict):
        extra = data.pop("extra")
        data.update(extra)
    sf = get_pg_session()
    with sf.Session() as session:
        saved = set_org_content_profile(session, tenant.tenant_id, data)
        session.commit()
    return {"profile": saved}


@router.post("/api/content/hotspots/dig")
async def api_dig_hotspots(
    body: HotspotBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        org = get_org_content_profile(session, tenant.tenant_id)
        result = dig_hotspots(
            adapter=body.adapter,  # type: ignore[arg-type]
            categories=body.categories,
            keywords=body.keywords,
            paste_text=body.paste_text,
            org_profile=org,
        )
        artifact_id = None
        if body.save:
            artifact_id = str(uuid.uuid4())
            session.add(
                ContentArtifact(
                    id=artifact_id,
                    tenant_id=tenant.tenant_id,
                    kind="hotspot",
                    title=f"热点 {result.get('count', 0)} 条",
                    body=result,
                    content_hash=result.get("content_hash"),
                )
            )
        session.commit()
    return {**result, "artifact_id": artifact_id}


@router.post("/api/content/scripts/generate")
async def api_generate_script(
    body: ScriptBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        style = resolve_style_for_generate(
            session, tenant.tenant_id, body.creator_id
        )
        org = get_org_content_profile(session, tenant.tenant_id)
        out = await generate_script(
            tenant_id=tenant.tenant_id,
            style=style,
            org_profile=org,
            hotspots=body.hotspots,
            duration_sec=body.duration_sec,
            platform=body.platform,
            extra_instruction=body.extra_instruction,
            student_names=body.student_names,
        )
        artifact_id = None
        if body.save:
            artifact_id = str(uuid.uuid4())
            title = (body.hotspots[0].get("title") if body.hotspots else None) or "口播稿"
            session.add(
                ContentArtifact(
                    id=artifact_id,
                    tenant_id=tenant.tenant_id,
                    kind="script",
                    title=str(title)[:200],
                    body=out,
                    creator_id=body.creator_id,
                )
            )
        session.commit()
    return {**out, "artifact_id": artifact_id}


@router.get("/api/content/artifacts")
async def api_list_artifacts(
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        q = session.query(ContentArtifact).filter(
            ContentArtifact.tenant_id == tenant.tenant_id
        )
        if kind:
            q = q.filter(ContentArtifact.kind == kind)
        rows = q.order_by(ContentArtifact.created_at.desc()).limit(limit).all()
        items = [
            {
                "id": r.id,
                "kind": r.kind,
                "title": r.title,
                "body": r.body,
                "content_hash": r.content_hash,
                "creator_id": r.creator_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {"items": items, "count": len(items)}
