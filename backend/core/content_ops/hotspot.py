"""Hotspot dig — manual activation; topic_agent / paste / seed."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

AdapterName = Literal["topic_agent", "paste", "seed"]

_SEED_HOTSPOTS: list[dict[str, Any]] = [
    {
        "title": "新学期家长最关心的三个入学问题",
        "summary": "入学适应、作息、家校沟通成为高频讨论点",
        "category": "教育",
        "score": 92,
    },
    {
        "title": "短视频时代，口播课如何留住前三秒",
        "summary": "开头抛痛点+具体数字，比堆形容词更有效",
        "category": "内容",
        "score": 88,
    },
    {
        "title": "暑假衔接班选题：习惯养成还是刷题？",
        "summary": "机构内容运营可对比两种卖点话术",
        "category": "教育",
        "score": 85,
    },
    {
        "title": "职场父母的晚托需求升温",
        "summary": "服务时段与安全保障成为转化关键",
        "category": "家长",
        "score": 80,
    },
    {
        "title": "AI 助教进课堂的家长疑虑清单",
        "summary": "隐私、准确度、替代真人是三大异议",
        "category": "科技",
        "score": 78,
    },
]


def content_hash(items: list[dict[str, Any]]) -> str:
    payload = json.dumps(items, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _filter_items(
    items: list[dict[str, Any]],
    *,
    categories: list[str] | None,
    keywords: str | None,
) -> list[dict[str, Any]]:
    cats = {c.strip() for c in (categories or []) if c and str(c).strip()}
    kws = [k.strip() for k in re.split(r"[,，\s]+", keywords or "") if k.strip()]
    out: list[dict[str, Any]] = []
    for it in items:
        if cats and str(it.get("category") or "") not in cats:
            continue
        if kws:
            blob = f"{it.get('title', '')} {it.get('summary', '')}"
            if not any(k in blob for k in kws):
                continue
        out.append(dict(it))
    return out


def _parse_paste(text: str) -> list[dict[str, Any]]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    items: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        # "1. title — summary" or plain title
        ln2 = re.sub(r"^\d+[\.\)、]\s*", "", ln)
        if "—" in ln2 or " - " in ln2:
            parts = re.split(r"\s*[—\-]\s*", ln2, maxsplit=1)
            title, summary = parts[0], (parts[1] if len(parts) > 1 else "")
        else:
            title, summary = ln2, ""
        items.append(
            {
                "title": title[:200],
                "summary": summary[:500],
                "category": "粘贴",
                "score": max(50, 100 - i),
            }
        )
    return items


def _topic_agent_items(
    *,
    org_profile: dict[str, Any],
    categories: list[str] | None,
    keywords: str | None,
) -> list[dict[str, Any]]:
    """Company-scoped topic synthesis without external crawl.

    Uses seed pool + org profile hints so results feel tenant-relevant.
    """
    industry = str(org_profile.get("industry") or "教育培训")
    focus = str(org_profile.get("product_focus") or org_profile.get("productFocus") or "")
    audience = str(
        org_profile.get("target_audience") or org_profile.get("targetAudience") or ""
    )
    base = [dict(x) for x in _SEED_HOTSPOTS]
    # Inject 1–2 org-flavored topics
    if focus or audience:
        base.insert(
            0,
            {
                "title": f"围绕「{focus or industry}」的本周内容选题",
                "summary": f"受众：{audience or '机构学员家长'}；结合公司定位产出口播切入点",
                "category": "教育",
                "score": 95,
            },
        )
    if keywords:
        base.insert(
            0,
            {
                "title": f"关键词「{keywords.strip()[:40]}」相关热点切入",
                "summary": f"结合{industry}场景，适合短视频口播展开",
                "category": (categories[0] if categories else "教育"),
                "score": 94,
            },
        )
    return _filter_items(base, categories=categories, keywords=None if focus else keywords)


def dig_hotspots(
    *,
    adapter: AdapterName = "topic_agent",
    categories: list[str] | None = None,
    keywords: str | None = None,
    paste_text: str | None = None,
    org_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return hotspot list + content_hash. Manual trigger only (no cron)."""
    org_profile = org_profile or {}
    adapter_l = str(adapter or "topic_agent").strip().lower()
    if adapter_l == "paste":
        items = _parse_paste(paste_text or "")
        if not items:
            items = _filter_items(
                _SEED_HOTSPOTS, categories=categories, keywords=keywords
            )
    elif adapter_l == "seed":
        items = _filter_items(_SEED_HOTSPOTS, categories=categories, keywords=keywords)
        if not items:
            items = list(_SEED_HOTSPOTS)
    else:
        # topic_agent (default)
        items = _topic_agent_items(
            org_profile=org_profile,
            categories=categories,
            keywords=keywords,
        )
        if not items:
            items = list(_SEED_HOTSPOTS)

    items = items[:12]
    return {
        "adapter": adapter_l,
        "items": items,
        "content_hash": content_hash(items),
        "count": len(items),
    }
