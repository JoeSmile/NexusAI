"""Task 45 — offerings catalog + content style / hotspot / script HTTP."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from packages.audit import write_audit_sync
from packages.content_ops.dig_persist import persist_dig_result
from packages.content_ops.hotspot import HotspotCrawlError, dig_hotspots
from packages.content_ops.offerings import get_offering, list_offerings
from packages.content_ops.script_gen import generate_script
from packages.content_ops.style import (
    DEFAULT_CREATOR_ID,
    delete_content_style,
    get_org_content_profile,
    list_content_styles,
    resolve_style_for_generate,
    set_org_content_profile,
    upsert_content_style,
)
from packages.content_ops.workflow_seed import ensure_builtin_hotspot_workflow
from backend.core.rate_limiter import check_endpoint_rate_limit
from backend.database.pgvector_session import ContentArtifact, get_pg_session
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext

router = APIRouter(tags=["content-ops"])

_DIG_PER_MIN = 30
_UPLOAD_PER_MIN = 10


def _enforce_rate(tenant_id: str, endpoint: str, per_min: int) -> None:
    retry = check_endpoint_rate_limit(tenant_id, endpoint, limit_per_min=per_min)
    if retry is not None:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_001", "message": "rate_limited"},
            headers={"Retry-After": str(retry)},
        )


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
    exclude_keywords: str | None = None
    paste_text: str | None = None
    industry: str | None = None
    region: str | None = None
    use_org_profile: bool = True
    user_note: str | None = None
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
    from packages.content_ops.style_extract import extract_style_from_text

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
    from packages.content_ops.file_text import (
        StyleUploadRejected,
        extract_text_from_bytes,
        validate_style_upload,
    )
    from packages.content_ops.style_extract import extract_style_from_text

    data = await file.read()
    _enforce_rate(tenant.tenant_id, "content_upload", _UPLOAD_PER_MIN)
    try:
        stored_name = validate_style_upload(
            filename=file.filename or "",
            content_type=file.content_type,
            data=data,
        )
    except StyleUploadRejected as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": e.message},
        ) from e
    try:
        text = extract_text_from_bytes(filename=stored_name, data=data)
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
    extracted["source_doc_ids"] = [stored_name]
    sf = get_pg_session()
    with sf.Session() as session:
        saved = upsert_content_style(session, tenant.tenant_id, creator_id, extracted)
        session.commit()
    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "action": "content_upload",
            "trace_id": "",
            "input_text": "",
            "output_text": stored_name,
        }
    )
    return {
        "style": saved,
        "chars": len(text),
        "filename": stored_name,
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
    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "action": "content_style_delete",
            "trace_id": "",
            "input_text": "",
            "output_text": creator_id,
        }
    )
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
    """Dig + 归一化合并进今日合集；同 content_hash 抓取记录幂等不重复落库。"""
    _enforce_rate(tenant.tenant_id, "content_dig", _DIG_PER_MIN)
    sf = get_pg_session()
    with sf.Session() as session:
        ensure_builtin_hotspot_workflow(
            session,
            tenant_id=tenant.tenant_id,
            created_by=tenant.user_id,
        )
        org = get_org_content_profile(session, tenant.tenant_id)
        try:
            result = dig_hotspots(
                adapter=body.adapter or "topic_agent",  # type: ignore[arg-type]
                categories=body.categories,
                keywords=body.keywords,
                exclude_keywords=body.exclude_keywords,
                paste_text=body.paste_text,
                org_profile=org,
                industry=body.industry,
                region=body.region,
                use_org_profile=body.use_org_profile,
                user_note=body.user_note,
            )
        except HotspotCrawlError as e:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "HOTSPOT_CRAWL_FAILED",
                    "message": str(e),
                    "crawl": e.crawl_meta,
                },
            ) from e
        out = persist_dig_result(
            session,
            tenant_id=tenant.tenant_id,
            result=result,
            save=body.save,
        )
        session.commit()
    return out


@router.post("/api/content/scripts/generate")
async def api_generate_script(
    body: ScriptBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    _enforce_rate(tenant.tenant_id, "content_generate", _DIG_PER_MIN)
    if not body.hotspots:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "REQ_001",
                "message": "hotspots_required",
            },
        )
    sf = get_pg_session()
    with sf.Session() as session:
        style = resolve_style_for_generate(
            session, tenant.tenant_id, body.creator_id
        )
        org = get_org_content_profile(session, tenant.tenant_id)
        from packages.content_ops.script_gen import build_script_prompt
        from backend.logging_config import get_logger

        _log = get_logger(__name__)
        _prompt = build_script_prompt(
            style=style or {},
            org_profile=org or {},
            hotspots=body.hotspots,
            duration_sec=body.duration_sec,
            platform=body.platform,
            extra_instruction=body.extra_instruction,
        )
        _log.info(
            "script.gen context tenant=%s creator=%s style_keys=%s org_keys=%s "
            "hotspots=%s duration=%s extra=%s\nprompt:\n%s",
            tenant.tenant_id,
            body.creator_id,
            list((style or {}).keys()),
            list((org or {}).keys()),
            [
                {"title": h.get("title"), "summary": (h.get("summary") or "")[:80]}
                for h in (body.hotspots or [])[:5]
            ],
            body.duration_sec,
            (body.extra_instruction or "")[:200],
            _prompt,
        )
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



class HotspotExcludeBody(BaseModel):
    title: str = Field(..., min_length=1)


@router.post("/api/content/hotspots/exclude")
async def exclude_hotspot_from_day(
    body: HotspotExcludeBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    """Soft-delete a title from today\'s hotspot pool; dig will skip it later."""
    from datetime import date

    from packages.content_ops.dig_persist import _title_excluded
    from packages.content_ops.hotspot import day_collection_hash

    day = date.today().isoformat()
    day_hash = day_collection_hash(tenant.tenant_id, day)
    sf = get_pg_session()
    with sf.Session() as session:
        day_row = (
            session.query(ContentArtifact)
            .filter(
                ContentArtifact.tenant_id == tenant.tenant_id,
                ContentArtifact.kind == "hotspot_day",
                ContentArtifact.content_hash == day_hash,
            )
            .one_or_none()
        )
        if day_row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "HOTSPOT_DAY_EMPTY", "message": "no_day_collection"},
            )
        body_obj = dict(day_row.body or {}) if isinstance(day_row.body, dict) else {}
        items = list(body_obj.get("items") or [])
        excluded = [str(x) for x in (body_obj.get("excluded") or []) if x]
        title = body.title.strip()
        kept = [
            it
            for it in items
            if not _title_excluded(str(it.get("title") or ""), [title])
        ]
        if title and not _title_excluded(title, excluded):
            excluded.append(title)
        body_obj["items"] = kept
        body_obj["count"] = len(kept)
        body_obj["excluded"] = excluded
        day_row.body = body_obj
        session.commit()
    return {
        "ok": True,
        "title": title,
        "remaining": len(kept),
        "excluded_count": len(excluded),
    }


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
