#!/usr/bin/env python3
"""网关量化基线 — Task 72 切片 5（D12）。

``--mock``：离线验证输出格式（LLM_PROVIDER=mock，TTFB 毫秒级无对比意义）。
``--live``：真实 harness 流式探测（需 LLM 可达 + 租户 Key）。
``--baseline`` / ``--compare``：同一环境前后对比。

Golden 集：``data/intent/golden/golden_v8.csv``（text 列，默认 20 条）。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_GOLDEN = ROOT / "data" / "intent" / "golden" / "golden_v8.csv"


def _load_prompts(path: Path, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            rows.append(
                {
                    "request_id": str(uuid.uuid4())[:8],
                    "prompt": text,
                    "label": (row.get("label") or "").strip(),
                }
            )
            if len(rows) >= limit:
                break
    return rows


async def _probe_one(
    *,
    prompt: str,
    request_id: str,
    tenant_id: str,
    mock: bool,
) -> dict[str, Any]:
    from backend.core.cost_manager import count_tokens
    from backend.core.harness import LLMHarness
    from backend.pipeline.graph import compiled_graph
    from backend.pipeline.state import make_initial_state

    if mock:
        os.environ.setdefault("LLM_PROVIDER", "mock")

    state = make_initial_state(tenant_id, "baseline-user", f"s-{request_id}", prompt)
    state["user_context"] = {
        "tenant_id": tenant_id,
        "user_id": "baseline-user",
        "permissions": [],
        "role": "user",
    }
    state["stream_mode"] = True

    t0 = time.perf_counter()
    final = await compiled_graph.ainvoke(state)
    graph_ms = (time.perf_counter() - t0) * 1000.0

    finish = str(final.get("finish_reason") or "")
    cache_hit = finish == "cache_hit"
    path = "short" if finish not in ("routed_to_llm",) else "long"

    ttfb_ms = graph_ms
    tokens = 0
    cost_usd = 0.0
    fallback = finish == "fallback"

    if path == "long" and finish == "routed_to_llm":
        harness = LLMHarness()
        model = final.get("selected_model") or "deepseek-v4-flash"
        messages = [{"role": "user", "content": prompt}]
        collected: list[str] = []
        async for tok in harness.stream(
            model=model,
            messages=messages,
            tenant_id=tenant_id,
            api_key=final.get("llm_api_key") or "",
            base_url=final.get("llm_base_url") or "",
            provider=final.get("llm_key_provider") or "default",
            max_tokens=200,
        ):
            if not collected:
                ttfb_ms = (time.perf_counter() - t0) * 1000.0
            collected.append(tok)
        text = "".join(collected)
        tokens = count_tokens(prompt) + count_tokens(text)
        from backend.core.cost_manager import calculate_cost

        cost_usd = float(calculate_cost(model, tokens))
        fr = harness.stream_finish_reason()
        if fr == "fallback":
            fallback = True
            finish = "fallback"

    return {
        "request_id": request_id,
        "ttfb_ms": round(ttfb_ms, 2),
        "graph_ms": round(graph_ms, 2),
        "tokens": tokens,
        "cost_usd": round(cost_usd, 6),
        "path": path,
        "cache_hit": cache_hit,
        "fallback": fallback,
        "finish_reason": finish,
    }


async def run_baseline(
    *,
    golden: Path,
    limit: int,
    tenant_id: str,
    mock: bool,
    format_only: bool = False,
) -> dict[str, Any]:
    prompts = _load_prompts(golden, limit)
    if format_only:
        results = [
            {
                "request_id": row["request_id"],
                "ttfb_ms": 0.0,
                "graph_ms": 0.0,
                "tokens": 0,
                "cost_usd": 0.0,
                "path": "format_only",
                "cache_hit": False,
                "fallback": False,
                "finish_reason": "format_only",
            }
            for row in prompts
        ]
        return {
            "summary": {
                "mode": "format_only",
                "count": len(results),
                "ttfb_p50_ms": 0.0,
                "ttfb_p99_ms": 0.0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "cache_hits": 0,
                "fallbacks": 0,
            },
            "results": results,
        }
    results: list[dict[str, Any]] = []
    for row in prompts:
        results.append(
            await _probe_one(
                prompt=row["prompt"],
                request_id=row["request_id"],
                tenant_id=tenant_id,
                mock=mock,
            )
        )

    ttfbs = [r["ttfb_ms"] for r in results if r["ttfb_ms"] is not None]
    summary = {
        "mode": "mock" if mock else "live",
        "count": len(results),
        "ttfb_p50_ms": round(statistics.median(ttfbs), 2) if ttfbs else 0.0,
        "ttfb_p99_ms": round(sorted(ttfbs)[int(len(ttfbs) * 0.99) - 1], 2)
        if len(ttfbs) >= 2
        else (ttfbs[0] if ttfbs else 0.0),
        "total_tokens": sum(int(r.get("tokens") or 0) for r in results),
        "total_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in results), 6),
        "cache_hits": sum(1 for r in results if r.get("cache_hit")),
        "fallbacks": sum(1 for r in results if r.get("fallback")),
    }
    return {"summary": summary, "results": results}


def _percent_delta(a: float, b: float) -> float | None:
    if a == 0:
        return None
    return round((b - a) / a * 100.0, 2)


def compare_baselines(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    bs = base.get("summary") or {}
    os_ = other.get("summary") or {}
    return {
        "baseline_mode": bs.get("mode"),
        "compare_mode": os_.get("mode"),
        "ttfb_p50_delta_pct": _percent_delta(
            float(bs.get("ttfb_p50_ms") or 0), float(os_.get("ttfb_p50_ms") or 0)
        ),
        "ttfb_p99_delta_pct": _percent_delta(
            float(bs.get("ttfb_p99_ms") or 0), float(os_.get("ttfb_p99_ms") or 0)
        ),
        "cost_delta_pct": _percent_delta(
            float(bs.get("total_cost_usd") or 0), float(os_.get("total_cost_usd") or 0)
        ),
        "cache_hits_delta": int(os_.get("cache_hits") or 0) - int(bs.get("cache_hits") or 0),
        "fallbacks_delta": int(os_.get("fallbacks") or 0) - int(bs.get("fallbacks") or 0),
    }


def _print_md(report: dict[str, Any]) -> None:
    summary = report.get("summary") or {}
    print("| metric | value |")
    print("|--------|-------|")
    for k, v in summary.items():
        print(f"| {k} | {v} |")
    print("\n| request_id | ttfb_ms | tokens | cost_usd | path | cache_hit | fallback |")
    print("|------------|---------|--------|----------|------|-----------|----------|")
    for r in report.get("results") or []:
        print(
            f"| {r.get('request_id')} | {r.get('ttfb_ms')} | {r.get('tokens')} | "
            f"{r.get('cost_usd')} | {r.get('path')} | {r.get('cache_hit')} | {r.get('fallback')} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="NexusAI gateway baseline (Task 72)")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--mock", action="store_true", help="LLM_PROVIDER=mock offline run")
    parser.add_argument(
        "--format-only",
        action="store_true",
        help="Offline: golden CSV + MD table only (no PG/LLM)",
    )
    parser.add_argument("--live", action="store_true", help="Real LLM stream probe")
    parser.add_argument("--baseline", type=Path, help="Write JSON baseline report")
    parser.add_argument("--compare", type=Path, help="Compare against saved baseline JSON")
    parser.add_argument("--md", action="store_true", help="Print markdown table to stdout")
    args = parser.parse_args()

    mock = args.mock or not args.live
    if args.live:
        mock = False

    report = asyncio.run(
        run_baseline(
            golden=args.golden,
            limit=max(1, args.limit),
            tenant_id=args.tenant,
            mock=mock,
            format_only=args.format_only,
        )
    )

    if args.baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote baseline → {args.baseline}")

    if args.compare:
        if not args.compare.is_file():
            raise SystemExit(f"compare file not found: {args.compare}")
        base = json.loads(args.compare.read_text(encoding="utf-8"))
        diff = compare_baselines(base, report)
        print(json.dumps(diff, ensure_ascii=False, indent=2))

    if args.md or (not args.baseline and not args.compare):
        _print_md(report)


if __name__ == "__main__":
    main()
