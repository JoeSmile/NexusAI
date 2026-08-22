"""Task 63 — RenderDirective extraction from orchestrator step_results."""

from __future__ import annotations

import json

from backend.core.render.directive import (
    ALLOWED_COMPONENTS,
    extract_render_directive,
    render_directive_to_dict,
)


def test_extract_hotspot_table_from_meta_result() -> None:
    items = [{"title": "A", "score": 90, "category": "考研"}]
    step_results = {
        "s1": {
            "ok": True,
            "capability_id": "hotspot.dig",
            "output": "{}",
            "meta": {
                "op": "hotspot.dig",
                "result": {"items": items, "day": "2026-08-22", "adapter": "topic_agent"},
            },
        }
    }
    directive = extract_render_directive(step_results)
    assert directive is not None
    assert directive.component == "hotspot_table"
    assert directive.payload["items"] == items
    assert directive.payload["day"] == "2026-08-22"
    dumped = render_directive_to_dict(directive)
    assert dumped["component"] in ALLOWED_COMPONENTS


def test_extract_hotspot_table_from_json_output() -> None:
    payload = {"items": [{"title": "B", "summary": "x"}], "count": 1}
    step_results = {
        "dig": {
            "ok": True,
            "capability_id": "hotspot.dig",
            "output": json.dumps(payload, ensure_ascii=False),
        }
    }
    directive = extract_render_directive(step_results)
    assert directive is not None
    assert len(directive.payload["items"]) == 1


def test_extract_skips_failed_or_empty() -> None:
    assert extract_render_directive(None) is None
    assert extract_render_directive({}) is None
    assert (
        extract_render_directive(
            {"s1": {"ok": False, "capability_id": "hotspot.dig", "output": "{}"}}
        )
        is None
    )
