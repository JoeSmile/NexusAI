"""步骤 params 引用解析（Task 56 切片 3）。"""

from __future__ import annotations

import json
from typing import Any


def _prior_output(step_results: dict[str, Any], step_id: str) -> Any:
    entry = step_results.get(step_id)
    if not isinstance(entry, dict):
        return entry
    if entry.get("skipped"):
        return None
    if "output" in entry:
        return entry["output"]
    return entry.get("text") or entry


def resolve_step_params(
    params: dict[str, Any],
    step_results: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """解析 source_step / lazy_doc_id 引用，产出 invoke payload。"""
    out = dict(params or {})
    source = out.pop("source_step", None)
    if source:
        prior = _prior_output(step_results, str(source))
        if prior is None:
            out.setdefault("message", "")
        elif isinstance(prior, str):
            out.setdefault("message", prior)
        else:
            out.setdefault("message", json.dumps(prior, ensure_ascii=False))

    lazy_doc_id = out.pop("lazy_doc_id", None)
    if lazy_doc_id and state:
        try:
            from packages.memory.memory_service import get_unified_memory_service

            svc = get_unified_memory_service(tenant_id=str(state.get("tenant_id") or "default"))
            doc = svc.load_document_by_id_sync(
                user_id=str(state.get("user_id") or ""),
                doc_id=str(lazy_doc_id),
            )
            if doc and doc.get("body"):
                out.setdefault("message", str(doc["body"])[:4000])
            else:
                out["lazy_load_unavailable"] = True
        except Exception:
            out["lazy_load_unavailable"] = True
    return out
