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
) -> dict[str, Any]:
    """解析 source_step 引用，产出 invoke payload。"""
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
    return out
