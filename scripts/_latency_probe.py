"""链路耗时排查：发真实请求测首 token/总时长（2026-09-05）。
用法: python scripts/_latency_probe.py  (需 /tmp/nexusai_token.txt 有 JWT)
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"  # noqa
import os
TOKEN = os.environ.get("NEXUSAI_TOKEN") or open(
    os.path.expanduser("~/nexusai_token.txt")
).read().strip()

CASES = [
    ("A2_greeting_你好", "你好", {"session_id": "probe_greet"}),
    ("A7_memory_自我介绍", "我叫小明，是做电商的", {"session_id": "probe_mem1"}),
    ("A7b_memory_我叫什么", "我叫什么名字？", {"session_id": "probe_mem1"}),
    ("B6_knowledge_报销", "查一下公司报销制度", {"session_id": "probe_kb"}),
    ("A3_content_口播稿", "帮我写个口播稿", {"session_id": "probe_content"}),
    ("complex_复合任务", "帮我写个口播稿，然后分析下这个热点", {"session_id": "probe_complex"}),
]

def sse_post(path: str, body: dict) -> dict:
    """POST + 流式读，返回 {first_token_ms, total_ms, first_chunk_ms, tokens, finish_reason}"""
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    t0 = time.time()
    first_chunk_ms = None
    first_token_ms = None
    buf = b""
    tokens = 0
    finish_reason = ""
    with urllib.request.urlopen(req, timeout=180) as resp:
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            now = time.time()
            if first_chunk_ms is None:
                first_chunk_ms = (now - t0) * 1000
            buf += chunk
            text = buf.decode("utf-8", errors="replace")
            # 粗略按行解析 token
            for line in text.split("\n"):
                if line.startswith("data: "):
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        if "token" in obj and isinstance(obj["token"], str):
                            if first_token_ms is None:
                                first_token_ms = (now - t0) * 1000
                            tokens += 1
                        if obj.get("type") == "done":
                            finish_reason = obj.get("finish_reason", "")
                            if first_token_ms is None:
                                first_token_ms = (now - t0) * 1000
    total_ms = (time.time() - t0) * 1000
    return {
        "first_chunk_ms": round(first_chunk_ms, 0) if first_chunk_ms else None,
        "first_token_ms": round(first_token_ms, 0) if first_token_ms else None,
        "total_ms": round(total_ms, 0),
        "tokens": tokens,
        "finish_reason": finish_reason,
    }

for name, msg, extra in CASES:
    body = {"message": msg, **extra, "user_id": "alice"}
    try:
        r = sse_post("/chat/streaming", body)
        print(f"{name:28s} first_token={r['first_token_ms']}ms total={r['total_ms']}ms tokens={r['tokens']} finish={r['finish_reason']}")
    except Exception as e:
        print(f"{name:28s} ERROR {type(e).__name__}: {e}")
