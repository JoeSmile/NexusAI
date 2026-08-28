"""Builtin tool handlers (Task 66 slice 1)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from packages.memory.memory_service import get_unified_memory_service
from backend.modules.notification.service import notify
from packages.auth.models import TenantContext
from packages.capability.exec_policy import resolve_exec_policy

logger = logging.getLogger(__name__)


async def invoke_builtin_handler(
    handler_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
    *,
    spec_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = resolve_exec_policy(spec_body)
    started = time.monotonic()
    try:
        result = await _dispatch(handler_id, payload, tenant)
    except Exception as exc:
        logger.warning("builtin handler %s failed: %s", handler_id, exc)
        return {
            "ok": False,
            "error": str(exc),
            "handler": handler_id,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if policy.timeout_s > 0 and elapsed_ms > policy.timeout_s * 1000:
        logger.warning(
            "builtin handler %s exceeded soft timeout %.1fs",
            handler_id,
            policy.timeout_s,
        )
    if isinstance(result, dict) and "ok" not in result:
        result = {"ok": True, "data": result}
    if isinstance(result, dict):
        result.setdefault("handler", handler_id)
        result.setdefault("elapsed_ms", elapsed_ms)
    return result


async def _dispatch(
    handler_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> dict[str, Any]:
    handlers = {
        "rag.search": _rag_search,
        "web.search": _web_search,
        "memory.search": _memory_search,
        "memory.write": _memory_write,
        "im.notify": _im_notify,
        "calendar.query": _calendar_query,
        "calendar.create": _calendar_create,
        "mail.draft": _mail_draft,
        "mail.send": _mail_send,
        "docx.generate": _docx_generate,
        "sql.query": _sql_query,
        "analytics.summary": _analytics_summary,
        "code.exec": _code_exec,
        "deploy.release": _deploy_release,
        "sys.metrics": _sys_metrics,
        "plan.status": _plan_status,
        "blackboard.search": _blackboard_search,
    }
    fn = handlers.get(handler_id)
    if fn is None:
        raise ValueError(f"unknown builtin handler: {handler_id}")
    return await fn(payload, tenant)


async def _rag_search(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    from packages.capability.invoke import _invoke_rag
    from packages.capability.models import CapabilityKind, CapabilityProvider, CapabilitySpec

    rag_spec = CapabilitySpec(
        id="rag.search",
        name="rag.search",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={
            "executor": "rag",
            "governance": True,
            "search_k": int(payload.get("search_k") or 3),
        },
    )
    frames: list[dict[str, Any]] = []
    async for frame in _invoke_rag(rag_spec, payload, tenant):
        frames.append(frame)
    text_parts: list[str] = []
    done: dict[str, Any] = {}
    for frame in frames:
        if frame.get("event") == "token":
            text_parts.append(str(frame.get("data") or ""))
        elif frame.get("event") == "done":
            done = frame.get("data") or {}
    return {
        "answer": "".join(text_parts) or done.get("answer", ""),
        "sources": done.get("sources", []),
        "knowledge_count": done.get("knowledge_count", 0),
    }


async def _web_search(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    url = payload.get("url")
    if url:
        from packages.security.url_guard import UrlValidationError, validate_base_url

        try:
            validate_base_url(str(url))
        except UrlValidationError as exc:
            raise ValueError(str(exc)) from exc
    return {
        "ok": True,
        "data": {
            "query": query,
            "results": [],
            "note": "web search provider not configured; SSRF guard applied",
        },
    }


async def _memory_search(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    limit = int(payload.get("limit") or 5)
    user_id = str(payload.get("user_id") or tenant.user_id or "anonymous")
    svc = get_unified_memory_service(tenant.tenant_id)
    items = await svc.search_warm(user_id, query, limit=limit)
    return {"items": items}


async def _memory_write(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    key = str(payload.get("key") or "").strip()
    value = str(payload.get("value") or "")
    user_id = str(payload.get("user_id") or tenant.user_id or "anonymous")
    if not key:
        raise ValueError("key required")
    svc = get_unified_memory_service(tenant.tenant_id)
    result = await svc.write("warm", user_id=user_id, key=key, value=value)
    return {"id": result.get("id"), "key": key, "tier": result.get("tier", "warm")}


async def _im_notify(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    notif_type = str(payload.get("type") or "info")
    summary = str(payload.get("summary") or "")
    user_id = str(payload.get("user_id") or tenant.user_id or "anonymous")
    refs = {k: v for k, v in payload.items() if k in ("run_id", "summary", "status")}
    if summary:
        refs["summary"] = summary
    channels = notify(tenant.tenant_id, user_id, notif_type, refs)
    return {"ok": True, "data": {"channels": channels, "type": notif_type}}


async def _calendar_query(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "events": [],
            "from": payload.get("from"),
            "to": payload.get("to"),
            "tenant_id": tenant.tenant_id,
        },
    }


async def _calendar_create(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "event_id": f"evt_stub_{int(time.time())}",
            "title": payload.get("title"),
            "start": payload.get("start"),
            "end": payload.get("end"),
        },
    }


async def _mail_draft(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    draft_id = f"draft_{tenant.tenant_id}_{int(time.time())}"
    return {
        "ok": True,
        "data": {
            "draft_id": draft_id,
            "to": payload.get("to"),
            "subject": payload.get("subject"),
            "status": "draft",
        },
    }


async def _mail_send(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "draft_id": payload.get("draft_id"),
            "status": "sent_stub",
        },
    }


async def _docx_generate(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "artifact_id": f"docx_{int(time.time())}",
            "template": payload.get("template"),
            "format": "docx",
        },
    }


async def _sql_query(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    sql = str(payload.get("sql") or "").strip().lower()
    if not sql.startswith("select"):
        raise ValueError("only SELECT statements allowed")
    forbidden = ("insert", "update", "delete", "drop", "alter", "truncate")
    if any(tok in sql for tok in forbidden):
        raise ValueError("mutating SQL not allowed")
    return {
        "ok": True,
        "data": {
            "rows": [],
            "row_count": 0,
            "sql_preview": sql[:120],
        },
    }


async def _analytics_summary(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "metric": payload.get("metric"),
            "window": payload.get("window", "7d"),
            "value": 0,
            "tenant_id": tenant.tenant_id,
        },
    }


async def _code_exec(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    language = str(payload.get("language") or "python")
    code = str(payload.get("code") or "")
    if len(code.encode("utf-8")) > 8_192:
        raise ValueError("code payload too large")
    return {
        "ok": True,
        "data": {
            "language": language,
            "stdout": "",
            "stderr": "",
            "note": "sandbox stub — no code executed",
        },
    }


async def _deploy_release(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "service": payload.get("service"),
            "version": payload.get("version"),
            "env": payload.get("env"),
            "status": "release_stub",
        },
    }


async def _sys_metrics(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    import os
    import sys

    return {
        "ok": True,
        "data": {
            "component": payload.get("component", "api"),
            "python": sys.version.split()[0],
            "pid": os.getpid(),
            "uptime_note": "stub metrics",
        },
    }


async def _plan_status(payload: dict[str, Any], tenant: TenantContext) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "run_id": payload.get("run_id"),
            "plan_id": payload.get("plan_id"),
            "status": "unknown",
            "nodes": [],
        },
    }


async def _blackboard_search(
    payload: dict[str, Any], tenant: TenantContext
) -> dict[str, Any]:
    from packages.plan.blackboard import Blackboard

    raw = payload.get("blackboard")
    if not isinstance(raw, list):
        raw = payload.get("entries") or []
    bb = Blackboard.from_state({"blackboard": raw})
    results = bb.search(
        topic=str(payload.get("topic") or "") or None,
        keyword=str(payload.get("keyword") or "") or None,
        min_confidence=float(payload.get("min_confidence") or 0.0),
        limit=int(payload.get("limit") or 12),
    )
    return {
        "ok": True,
        "entries": results,
        "count": len(results),
    }


def builtin_result_to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
