"""Query 重写解析/消毒（Task 56）— 无独立 LLM；由 task_plan 同次调用产出。"""

from __future__ import annotations

import re
from typing import Any

from backend.core.plan.models import QueryRewrite

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|token|bearer\s+\S+|sk-[a-z0-9]{8,})"
)
_MAX_REWRITE_LEN = 2000


def sanitize_rewritten_query(text: str, *, fallback: str) -> str:
    raw = (text or "").strip() or (fallback or "").strip()
    if _SECRET_RE.search(raw):
        raw = fallback or raw
    return raw[:_MAX_REWRITE_LEN]


def parse_query_rewrite(
    raw: Any,
    *,
    original_message: str,
) -> QueryRewrite | None:
    """从 plan 根或子对象解析 query_rewrite；失败返回 None（降级）。"""
    if not isinstance(raw, dict):
        return None
    try:
        data = dict(raw)
        rq = data.get("rewritten_query") or original_message
        data["rewritten_query"] = sanitize_rewritten_query(
            str(rq), fallback=original_message
        )
        subs = data.get("sub_queries") or []
        if subs and isinstance(subs[0], dict):
            data["sub_queries"] = [
                str(x.get("query") or x.get("id") or "")[:500]
                for x in subs
                if isinstance(x, dict)
            ]
        elif isinstance(subs, list):
            data["sub_queries"] = [str(x)[:500] for x in subs if str(x).strip()]
        else:
            data["sub_queries"] = []
        return QueryRewrite.model_validate(data)
    except Exception:
        return None


def attach_query_rewrite_to_plan(
    plan: dict[str, Any],
    *,
    original_message: str,
) -> dict[str, Any]:
    """确保 plan 含 query_rewrite；缺失则用原始 message 降级。"""
    qr = parse_query_rewrite(plan.get("query_rewrite"), original_message=original_message)
    if qr is None:
        qr = QueryRewrite(
            rewritten_query=sanitize_rewritten_query(
                original_message, fallback=original_message
            ),
            sub_queries=[],
            language="zh",
            clarification_needed=False,
        )
    out = dict(plan)
    out["query_rewrite"] = qr.model_dump(mode="json")
    if not out.get("goal"):
        out["goal"] = qr.rewritten_query[:2000]
    return out
