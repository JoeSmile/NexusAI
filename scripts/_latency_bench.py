"""链路延迟量化：每类请求跑 N 次取中位数（2026-09-05 排查补充）。
用法: NEXUSAI_TOKEN=<jwt> uv run --no-sync python scripts/_latency_bench.py
"""
import json
import os
import statistics
import time
import urllib.request
import uuid

TOKEN = open(os.path.expanduser("~/nexusai_token.txt")).read().strip()
BASE = "http://127.0.0.1:8000"

CASES = [
    ("greeting_缓存命中", "你好"),
    ("memory_自我介绍", "我叫小明，是做电商的"),
    ("knowledge_报销", "查一下公司报销制度"),
    ("script_口播稿", "帮我写个口播稿"),
]


def run_once(msg: str, n: int):
    sid = f"bench_{uuid.uuid4().hex[:8]}"
    req = urllib.request.Request(
        f"{BASE}/chat/streaming",
        data=json.dumps({"message": msg, "session_id": sid, "user_id": "alice"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    t0 = time.time()
    first = None
    tokens = 0
    with urllib.request.urlopen(req, timeout=180) as r:
        while True:
            c = r.read(8192)
            if not c:
                break
            now = time.time()
            if first is None:
                first = (now - t0) * 1000
            txt = c.decode("utf-8", errors="replace")
            tokens += txt.count('"token"')
    total = (time.time() - t0) * 1000
    return first, total, tokens


for name, msg in CASES:
    firsts, totals, tok_lists = [], [], []
    for i in range(3):
        try:
            f, t, tk = run_once(msg, i)
            firsts.append(f)
            totals.append(t)
            tok_lists.append(tk)
        except Exception as e:
            print(f"{name} run{i} ERROR {e}")
    if firsts:
        print(
            f"{name:24s} 首token中位={statistics.median(firsts):.0f}ms "
            f"(range {min(firsts):.0f}-{max(firsts):.0f}) "
            f"总时中位={statistics.median(totals):.0f}ms "
            f"tokens中位={statistics.median(tok_lists)}"
        )
