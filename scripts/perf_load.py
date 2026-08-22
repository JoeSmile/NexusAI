"""NexusAI 压测脚本 — 三个端点 × 多并发档位, 输出 QPS/P50/P95/P99/错误率。

用法: python perf_load.py [--base http://localhost:8000]
"""
import argparse
import asyncio
import json
import statistics
import time

import httpx

BASE = "http://localhost:8000"


async def worker(client: httpx.AsyncClient, endpoint: str, payload: dict | None,
                 jwt: str, n: int, results: list, tag: str) -> None:
    headers = {"Authorization": f"Bearer {jwt}"}
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            if payload is not None:
                r = await client.post(endpoint, json=payload, headers=headers)
            else:
                r = await client.get(endpoint, headers=headers)
            dt = (time.perf_counter() - t0) * 1000
            results.append((tag, dt, r.status_code))
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            results.append((tag, dt, -1))


async def load_test(endpoint: str, payload: dict | None, jwt: str,
                    concurrency: int, total: int) -> dict:
    results: list = []
    per_worker = max(1, total // concurrency)
    async with httpx.AsyncClient(timeout=60, base_url=BASE) as client:
        await asyncio.gather(*[
            worker(client, endpoint, payload, jwt, per_worker, results, "w")
            for _ in range(concurrency)
        ])
    lats = [r[1] for r in results]
    errs = [r for r in results if r[2] != 200]
    ok = len(results) - len(errs)
    total_s = (max(lats) if lats else 0) / 1000
    qps = ok / total_s if total_s > 0 else 0
    lat_sorted = sorted(lats)
    def pct(p):
        if not lat_sorted:
            return 0.0
        return lat_sorted[min(len(lat_sorted) - 1, int(len(lat_sorted) * p))]
    return {
        "endpoint": endpoint,
        "concurrency": concurrency,
        "requests": len(results),
        "ok": ok,
        "errors": len(errs),
        "qps": round(qps, 1),
        "p50_ms": round(pct(0.50), 1),
        "p95_ms": round(pct(0.95), 1),
        "p99_ms": round(pct(0.99), 1),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    base = args.base

    print(f"=== NexusAI 压测 base={base} ===")
    # 预登录拿 JWT
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{base}/api/auth/login",
                         json={"username": "alice", "password": "123456"})
        if r.status_code != 200:
            print("login failed:", r.status_code, r.text[:200])
            return
        jwt = r.json()["access_token"]
        print("login OK, jwt len:", len(jwt))

    chat_payload = {"session_id": "load-test", "message": "你好，介绍一下你自己",
                    "model": "deepseek-chat"}
    targets = [
        ("GET  /api/llm/available-models", None),
        ("POST /chat/streaming (mock)", chat_payload),
    ]
    for conc in (10, 50, 100):
        print(f"\n--- 并发 {conc} ---")
        for name, payload in targets:
            total = conc * 20
            res = await load_test(payload and "/chat/streaming" or "/api/llm/available-models",
                                  payload, jwt, conc, total)
            print(f"{name}: QPS={res['qps']} ok={res['ok']}/{res['requests']} "
                  f"err={res['errors']} p50={res['p50_ms']}ms p95={res['p95_ms']}ms p99={res['p99_ms']}ms")


if __name__ == "__main__":
    asyncio.run(main())
