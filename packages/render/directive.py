"""RenderDirective — backend tells FE which registered component to mount."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

ALLOWED_COMPONENTS = frozenset({"hotspot_table"})
_HOTSPOT_CAP_IDS = frozenset({"hotspot.dig", "content.hotspot_dig"})
_MAX_HOTSPOT_ROWS = 100


class RenderDirective(BaseModel):
    component: str
    payload: dict[str, Any] = Field(default_factory=dict)


def render_directive_to_dict(directive: RenderDirective) -> dict[str, Any]:
    if directive.component not in ALLOWED_COMPONENTS:
        return {}
    return directive.model_dump(mode="json")


def _hotspot_items_from_step(res: dict[str, Any]) -> list[dict[str, Any]] | None:
    meta = res.get("meta")
    if isinstance(meta, dict):
        result = meta.get("result")
        if isinstance(result, dict):
            items = result.get("items")
            if isinstance(items, list) and items:
                return [it for it in items if isinstance(it, dict)]
    raw = str(res.get("output") or res.get("text") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    items = parsed.get("items")
    if isinstance(items, list) and items:
        return [it for it in items if isinstance(it, dict)]
    return None


def _build_hotspot_table(items: list[dict[str, Any]], *, meta: dict[str, Any]) -> RenderDirective:
    trimmed = items[:_MAX_HOTSPOT_ROWS]
    payload: dict[str, Any] = {
        "items": trimmed,
        "count": len(trimmed),
    }
    for key in ("day", "content_hash", "adapter"):
        if meta.get(key) is not None:
            payload[key] = meta[key]
    return RenderDirective(component="hotspot_table", payload=payload)


def extract_render_directive(step_results: dict[str, Any] | None) -> RenderDirective | None:
    """Pick the latest hotspot.dig step and emit a whitelisted render directive."""
    if not step_results:
        return None
    last: RenderDirective | None = None
    for res in step_results.values():
        if not isinstance(res, dict) or not res.get("ok"):
            continue
        cap = str(res.get("capability_id") or "")
        op = ""
        meta = res.get("meta")
        if isinstance(meta, dict):
            op = str(meta.get("op") or "")
        if cap not in _HOTSPOT_CAP_IDS and op not in _HOTSPOT_CAP_IDS:
            if "hotspot" not in cap and "hotspot" not in op:
                continue
        items = _hotspot_items_from_step(res)
        if not items:
            continue
        result_meta: dict[str, Any] = {}
        if isinstance(meta, dict):
            result = meta.get("result")
            if isinstance(result, dict):
                result_meta = result
        last = _build_hotspot_table(items, meta=result_meta)
    return last
