"""Task 45 gold line 9' — importable replay."""

from __future__ import annotations

import pytest

try:
    from examples.qa.journeys.content_ops_gold_line import run_gold_line
    from examples.qa.journeys.content_ops_gold_line_http import run_http_gold_line
except ModuleNotFoundError:
    pytest.skip("examples/qa/journeys not present", allow_module_level=True)


@pytest.mark.asyncio
async def test_content_ops_gold_line() -> None:
    out = await run_gold_line()
    assert out["hotspot_count"] >= 1
    assert int(out["script_chars"]) > 0
    art = out["artifact"]
    assert isinstance(art, dict)
    assert "李明" not in str(art.get("body") or "")


def test_content_ops_gold_line_http() -> None:
    import requests

    try:
        out = run_http_gold_line()
    except requests.ConnectionError:
        pytest.skip("NexusAI API not running on NEXUSAI_BASE_URL")
    except RuntimeError as exc:
        msg = str(exc)
        if "cannot reach" in msg or "login HTTP" in msg:
            pytest.skip(f"live API not ready: {msg[:200]}")
        raise
    assert int(out["hotspot_count"]) >= 1
    assert int(out["script_chars"]) > 0
