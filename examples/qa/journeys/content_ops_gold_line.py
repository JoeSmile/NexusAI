"""Content ops gold line 9' — replayable without live crawl.

Sequence: offerings (implemented hotspot + script) → default style → seed
hotspots → script.gen (G7 name redaction) → artifact-shaped result.

Keeps a companion HTTP journey for a running API:
    uv run python examples/qa/journeys/content_ops_gold_line_http.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.content_ops.hotspot import dig_hotspots
from backend.core.content_ops.offerings import DEFAULT_OFFERINGS
from backend.core.content_ops.script_gen import generate_script
from backend.core.content_ops.style import DEFAULT_CONTENT_STYLE, resolve_style_for_generate
from backend.core.memory_service import redact_student_names_in_text


def _assert_offerings() -> None:
    ids = {o["id"] for o in DEFAULT_OFFERINGS}
    implemented = [o for o in DEFAULT_OFFERINGS if o["status"] == "implemented"]
    assert "wf.hotspot_dig" in ids
    assert "wf.script_gen" in ids
    assert all(o.get("target_id") for o in implemented)


def _assert_default_style() -> None:
    class _S:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def one_or_none(self):
            return None

    style = resolve_style_for_generate(_S(), "gold-tenant", None)
    assert style.get("is_default") is True
    assert style["persona"] == DEFAULT_CONTENT_STYLE["persona"]


def _assert_g7() -> None:
    out = redact_student_names_in_text(
        "请联系李明家长确认入学",
        tenant_id="gold-tenant",
        names=["李明"],
    )
    assert "李明" not in out


async def run_gold_line() -> dict[str, object]:
    _assert_offerings()
    _assert_default_style()
    _assert_g7()

    hot = dig_hotspots(adapter="seed", categories=["K12"])
    assert hot["count"] >= 1
    items = list(hot.get("items") or [])
    assert items[0].get("title")

    script = await generate_script(
        tenant_id="gold-tenant",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={"name": "金线教培", "product_focus": "K12 入学适应"},
        hotspots=items[:2],
        duration_sec=60,
        platform="douyin",
        student_names=["李明"],
        model="mock-local",
    )
    body = str(script.get("script") or "")
    assert body.strip()
    assert "李明" not in body
    assert script.get("style_is_default") is True

    artifact = {
        "kind": "script",
        "title": items[0].get("title"),
        "body": body,
        "student_pii_redacted": script.get("student_pii_redacted"),
    }
    return {
        "hotspot_count": hot["count"],
        "script_chars": len(body),
        "artifact": artifact,
        "offerings": ["wf.hotspot_dig", "wf.script_gen"],
    }


def main() -> int:
    result = asyncio.run(run_gold_line())
    print("GOLD_LINE_OK")
    print(
        f"hotspots={result['hotspot_count']} "
        f"script_chars={result['script_chars']} "
        f"offerings={result['offerings']}"
    )
    print(
        "FE_SHELL: /workspace memory-panel -> hotspot dig -> script gen "
        "(ContentStudio / HomeChat shortcuts)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        print(f"GOLD_LINE_FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
