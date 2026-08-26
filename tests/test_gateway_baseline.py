"""Task 72 切片 5 — gateway_baseline 脚本单元。"""

from __future__ import annotations

import asyncio

import pytest

from scripts.gateway_baseline import DEFAULT_GOLDEN, _load_prompts, compare_baselines, run_baseline


def test_load_prompts_from_golden() -> None:
    if not DEFAULT_GOLDEN.is_file():
        pytest.skip("golden_v8.csv missing")
    rows = _load_prompts(DEFAULT_GOLDEN, limit=3)
    assert len(rows) == 3
    assert rows[0]["prompt"]
    assert rows[0]["request_id"]


def test_format_only_report() -> None:
    if not DEFAULT_GOLDEN.is_file():
        pytest.skip("golden_v8.csv missing")
    report = asyncio.run(
        run_baseline(
            golden=DEFAULT_GOLDEN,
            limit=2,
            tenant_id="default",
            mock=True,
            format_only=True,
        )
    )
    assert report["summary"]["mode"] == "format_only"
    assert len(report["results"]) == 2


def test_compare_baselines_delta() -> None:
    base = {
        "summary": {
            "mode": "mock",
            "ttfb_p50_ms": 100.0,
            "ttfb_p99_ms": 200.0,
            "total_cost_usd": 0.01,
            "cache_hits": 1,
            "fallbacks": 0,
        }
    }
    other = {
        "summary": {
            "mode": "mock",
            "ttfb_p50_ms": 110.0,
            "ttfb_p99_ms": 180.0,
            "total_cost_usd": 0.008,
            "cache_hits": 2,
            "fallbacks": 1,
        }
    }
    diff = compare_baselines(base, other)
    assert diff["ttfb_p50_delta_pct"] == 10.0
    assert diff["cache_hits_delta"] == 1
    assert diff["fallbacks_delta"] == 1
