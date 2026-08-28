"""Capability Hub executor=content_ops — hotspot.dig / script.gen."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from packages.auth.models import TenantContext
from backend.core.capability.models import CapabilitySpec
from backend.core.content_ops.hotspot import HotspotCrawlError, dig_hotspots
from backend.core.content_ops.script_gen import generate_script
from backend.core.content_ops.style import (
    get_org_content_profile,
    resolve_style_for_generate,
)
from backend.database.pgvector_session import get_pg_session


def _payload_list(payload: dict[str, Any], key: str) -> list[Any]:
    raw = payload.get(key)
    if isinstance(raw, list):
        return raw
    return []


async def invoke_content_ops(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    """Dispatch by capability id (or spec.op)."""
    op = str((spec.spec or {}).get("op") or spec.id).strip()
    tid = tenant.tenant_id

    if op in ("hotspot.dig", "content.hotspot_dig"):
        adapter = str(payload.get("adapter") or "topic_agent")
        categories = payload.get("categories")
        if isinstance(categories, str):
            categories = [categories]
        if not isinstance(categories, list):
            categories = None
        save = payload.get("save")
        if save is None:
            save = True
        sf = get_pg_session()
        with sf.Session() as session:
            org = get_org_content_profile(session, tid)
            try:
                result = dig_hotspots(
                    adapter=adapter,  # type: ignore[arg-type]
                    categories=categories,
                    keywords=payload.get("keywords"),
                    paste_text=payload.get("paste_text") or payload.get("paste"),
                    org_profile=org,
                    industry=payload.get("industry"),
                    region=payload.get("region"),
                    use_org_profile=bool(payload.get("use_org_profile", True)),
                    user_note=payload.get("user_note"),
                )
            except HotspotCrawlError as e:
                yield {
                    "event": "error",
                    "data": {
                        "code": "HOTSPOT_CRAWL_FAILED",
                        "message": str(e),
                        "crawl": e.crawl_meta,
                    },
                    "cost_source": "invoke",
                }
                return
            from backend.core.content_ops.dig_persist import persist_dig_result

            result = persist_dig_result(
                session,
                tenant_id=tid,
                result=result,
                save=bool(save),
            )
            session.commit()
        text = json.dumps(result, ensure_ascii=False)
        yield {"event": "token", "data": text, "cost_source": "invoke"}
        yield {
            "event": "done",
            "data": {
                "capability_id": spec.id,
                "kind": "tool",
                "op": "hotspot.dig",
                "result": result,
            },
            "cost_source": "invoke",
        }
        return

    if op in ("script.gen", "content.script_gen"):
        creator_id = str(payload.get("creator_id") or "default")
        hotspots = _payload_list(payload, "hotspots")
        if not hotspots and payload.get("hotspot"):
            hotspots = [payload["hotspot"]]
        sf = get_pg_session()
        with sf.Session() as session:
            style = resolve_style_for_generate(session, tid, creator_id)
            org = get_org_content_profile(session, tid)
        names = payload.get("student_names")
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list):
            names = None
        out = await generate_script(
            tenant_id=tid,
            style=style,
            org_profile=org,
            hotspots=[h for h in hotspots if isinstance(h, dict)],
            duration_sec=int(payload.get("duration_sec") or 60),
            platform=str(payload.get("platform") or "短视频"),
            extra_instruction=str(payload.get("extra_instruction") or ""),
            student_names=names,
            warm=payload.get("warm") if isinstance(payload.get("warm"), dict) else None,
            model=str(payload.get("model") or "") or None,
        )
        yield {"event": "token", "data": out["script"], "cost_source": "invoke"}
        yield {
            "event": "done",
            "data": {
                "capability_id": spec.id,
                "kind": "tool",
                "op": "script.gen",
                "result": out,
                "student_pii_redacted": out.get("student_pii_redacted"),
            },
            "cost_source": "invoke",
        }
        return

    if op in ("style.extract", "creator.style_extract"):
        from backend.core.content_ops.style import upsert_content_style
        from backend.core.content_ops.style_extract import extract_style_from_text

        creator_id = str(payload.get("creator_id") or "default")
        text = str(
            payload.get("text")
            or payload.get("transcript")
            or payload.get("content")
            or ""
        )
        save = bool(payload.get("save", True))
        extracted = await extract_style_from_text(
            tenant_id=tid,
            creator_id=creator_id,
            text=text,
            model=str(payload.get("model") or "") or None,
        )
        if save and text.strip():
            sf = get_pg_session()
            with sf.Session() as session:
                saved = upsert_content_style(session, tid, creator_id, extracted)
                session.commit()
                extracted = saved
        blob = json.dumps(extracted, ensure_ascii=False)
        yield {"event": "token", "data": blob, "cost_source": "invoke"}
        yield {
            "event": "done",
            "data": {
                "capability_id": spec.id,
                "kind": "tool",
                "op": "style.extract",
                "result": extracted,
            },
            "cost_source": "invoke",
        }
        return

    yield {
        "event": "error",
        "data": {"message": "unsupported_content_ops", "op": op},
        "cost_source": "invoke",
    }
