"""RAG 两级缓存 — L1 答案 + L2 embedding(Task 29)

redis 不可用时静默降级,绝不因缓存导致 500。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import struct
import time
import unicodedata
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

EMBED_CACHE_DIM = 768
L1_MAX_AGE_SEC = 4 * 3600
CACHE_VERSION = 1

_stats = {"l1_hit": 0, "l1_miss": 0, "l2_hit": 0, "l2_miss": 0}


def _env_bool(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except ValueError:
        return default


def _inc_metric(kind: str, cache_type: str, tenant: str = "*") -> None:
    """Prometheus 埋点(kind=hit|miss);指标缺失/失败不得影响业务。"""
    try:
        from backend.core.metrics import cache_hits, cache_misses

        counter = cache_hits if kind == "hit" else cache_misses
        counter.labels(tenant=tenant, cache_type=cache_type).inc()
    except Exception:
        pass


def rag_cache_enabled() -> bool:
    return _env_bool("RAG_CACHE_ENABLED", True)


def normalize(text: str) -> str:
    """轻量无损归一化:NFKC + lower + 折叠空白。不做同义词改写。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def norm_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:16]


def contains_pii(text: str) -> bool:
    from backend.core.guardrails.pii_patterns import PII_PATTERNS

    for pattern in PII_PATTERNS.values():
        if re.search(pattern, text or ""):
            return True
    return False


def get_redis():
    """惰性同步 redis 客户端;失败返回 None(静默降级)。"""
    if not rag_cache_enabled():
        return None
    from backend.core.redis_tools import get_sync_redis

    return get_sync_redis(decode_responses=False)


def reset_redis_for_tests() -> None:
    """测试用:重置惰性连接与失败标志。"""
    global _stats
    from backend.core.redis_tools import reset_redis_clients_for_tests

    reset_redis_clients_for_tests()
    _stats = {"l1_hit": 0, "l1_miss": 0, "l2_hit": 0, "l2_miss": 0}


def pack_embed_768(vec: list[float]) -> bytes:
    # EMBED_CACHE_DIM 必须与 EMBEDDING_DIMENSIONS 配置一致(L2 只缓存 API 原始维);
    # 当前固定 768(text-embedding-v3 配置值),改维度时需同步此常量与 DB 列(1536 补零)。
    data = vec[:EMBED_CACHE_DIM] + [0.0] * (EMBED_CACHE_DIM - len(vec[:EMBED_CACHE_DIM]))
    return struct.pack(f"<{EMBED_CACHE_DIM}f", *data)


def unpack_embed_768(raw: bytes) -> list[float]:
    if len(raw) != EMBED_CACHE_DIM * 4:
        raise ValueError("bad embed cache blob")
    return list(struct.unpack(f"<{EMBED_CACHE_DIM}f", raw))


# ── L2 embedding ──


def l2_key(model: str, text: str) -> str:
    # key 与 embed 输入一致:API 只嵌入前 8000 字符(normalize 后截断),超长文本避免哈希错位
    return f"rag:e:{model}:{norm_hash(text[:8000])}"


def l2_get(model: str, text: str) -> list[float] | None:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get(l2_key(model, text))
        if not raw:
            return None
        vec = unpack_embed_768(raw)
        ttl = _env_int("RAG_CACHE_TTL_EMBED", 86400)
        r.expire(l2_key(model, text), ttl)  # 滑动续期
        _stats["l2_hit"] += 1
        _inc_metric("hit", "rag_embed")
        return vec
    except Exception as e:
        logger.debug("L2 get failed: %s", e)
        return None


def l2_probe(model: str, text: str) -> list[float] | None:
    """只读探测 L2(不计 hit/miss、不续期)——成本预估等无副作用场景。"""
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get(l2_key(model, text))
        if not raw:
            return None
        return unpack_embed_768(raw)
    except Exception:
        return None


def l2_set(model: str, text: str, vec: list[float]) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        ttl = _env_int("RAG_CACHE_TTL_EMBED", 86400)
        # 只缓存 API 维(≤768);已是 1536 补零的话取前 768
        r.set(l2_key(model, text), pack_embed_768(vec), ex=ttl)
    except Exception as e:
        logger.debug("L2 set failed: %s", e)


def record_l2_miss() -> None:
    _stats["l2_miss"] += 1
    _inc_metric("miss", "rag_embed")


def estimate_embedding_cost_if_miss(norm_q: str) -> float:
    """L2 未命中时的单次 embedding 成本预估(美元);redis 不可用或 L2 命中为 0。

    用 l2_probe 只读探测——不计 hit/miss,避免污染 status 命中率(l2_hit 双计问题)。
    """
    from backend.core.cost_manager import _price, count_tokens
    from backend.core.model_registry import select_embedding_model

    try:
        if get_redis() is None:
            return 0.0
        spec = select_embedding_model()
        if l2_probe(spec.name, norm_q) is not None:
            return 0.0
        return count_tokens(norm_q) * _price(spec.name) / 1000.0
    except Exception:
        return 0.0


# ── L1 answer + epoch ──


def epoch_key(tenant_id: str) -> str:
    return f"rag:epoch:{tenant_id or 'default'}"


def get_epoch(tenant_id: str) -> int:
    r = get_redis()
    if r is None:
        return 0
    try:
        v = r.get(epoch_key(tenant_id))
        return int(v) if v else 0
    except Exception:
        return 0


def bump_epoch(tenant_id: str = "default") -> int:
    r = get_redis()
    if r is None:
        return 0
    try:
        return int(r.incr(epoch_key(tenant_id)))
    except Exception as e:
        logger.debug("epoch bump failed: %s", e)
        return 0


def l1_key(tenant_id: str, question: str) -> str:
    ep = get_epoch(tenant_id)
    return f"rag:a:{ep}:{tenant_id or 'default'}:{norm_hash(question)}"


def l1_get(tenant_id: str, question: str) -> dict[str, Any] | None:
    r = get_redis()
    if r is None:
        return None
    if contains_pii(question):
        return None
    key = l1_key(tenant_id, question)
    try:
        raw = r.get(key)
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        created = float(data.get("created_at") or 0)
        age = time.time() - created if created else 0
        if age > L1_MAX_AGE_SEC:
            r.delete(key)
            return None
        # 滑动续期,不超过 4h 剩余
        base_ttl = _env_int("RAG_CACHE_TTL_ANSWER", 3600)
        remain_cap = max(1, int(L1_MAX_AGE_SEC - age))
        r.expire(key, min(base_ttl, remain_cap))
        _stats["l1_hit"] += 1
        _inc_metric("hit", "rag_answer", tenant_id or "default")
        return data
    except Exception as e:
        logger.debug("L1 get failed: %s", e)
        return None


def l1_set(tenant_id: str, question: str, payload: dict[str, Any]) -> None:
    r = get_redis()
    if r is None:
        return
    if contains_pii(question):
        return
    try:
        body = {
            "answer": payload.get("answer", ""),
            "sources": payload.get("sources", []),
            "question": payload.get("question", question),
            "knowledge_count": payload.get("knowledge_count", 0),
            "created_at": time.time(),
            "cache_version": CACHE_VERSION,
        }
        ttl = _env_int("RAG_CACHE_TTL_ANSWER", 3600)
        r.set(
            l1_key(tenant_id, question),
            json.dumps(body, ensure_ascii=False).encode("utf-8"),
            ex=ttl,
        )
    except Exception as e:
        logger.debug("L1 set failed: %s", e)


def record_l1_miss(tenant_id: str = "default") -> None:
    _stats["l1_miss"] += 1
    _inc_metric("miss", "rag_answer", tenant_id or "default")


# ── 单飞锁 ──


def acquire_lock(key: str, ttl: int = 10) -> bool:
    r = get_redis()
    if r is None:
        return True  # 无 redis:当作拿到锁,直接算
    try:
        return bool(r.set(f"rag:lock:{key}", b"1", nx=True, ex=ttl))
    except Exception:
        return True


def release_lock(key: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(f"rag:lock:{key}")
    except Exception:
        pass


def wait_l1(tenant_id: str, question: str, timeout_ms: int = 500) -> dict[str, Any] | None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        hit = l1_get(tenant_id, question)
        if hit:
            return hit
        time.sleep(0.05)
    return None


# ── 限流 ──


def _minute_bucket() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M")


def check_rate_limit(tenant_id: str, *, miss: bool = False) -> None:
    """超限抛 ContextGateException RATE_001。"""
    from backend.core.errors import ContextGateException, ErrorCode

    r = get_redis()
    if r is None:
        return
    tid = tenant_id or "default"
    if miss:
        limit = _env_int("RAG_RATE_LIMIT_MISS", 10)
        key = f"rl:rag:miss:{tid}:{_minute_bucket()}"
    else:
        limit = _env_int("RAG_RATE_LIMIT_REQ", 60)
        key = f"rl:rag:req:{tid}:{_minute_bucket()}"
    try:
        n = int(r.incr(key))
        if n == 1:
            r.expire(key, 70)
        if n > limit:
            raise ContextGateException(
                ErrorCode.RATE_LIMITED.value,
                "rate_limited",
                detail=f"{'miss' if miss else 'req'}>{limit}/min",
            )
    except ContextGateException:
        raise
    except Exception as e:
        logger.debug("rate limit check skipped: %s", e)


def _scan_count(r, pattern: str, max_keys: int = 5000) -> tuple[int, bool]:
    """可控 SCAN 计数;超过 max_keys 截断并标记 capped(避免 KEYS *)。"""
    n = 0
    cursor: int | bytes = 0
    capped = False
    try:
        while True:
            cursor, keys = r.scan(cursor=cursor, match=pattern, count=200)
            n += len(keys or [])
            if n >= max_keys:
                return max_keys, True
            if cursor == 0 or cursor == b"0":
                break
    except Exception as e:
        logger.debug("scan count failed (%s): %s", pattern, e)
        return 0, False
    return n, capped


def cache_stats_snapshot() -> dict[str, Any]:
    hits = _stats["l1_hit"] + _stats["l2_hit"]
    misses = _stats["l1_miss"] + _stats["l2_miss"]
    total = hits + misses
    l1_entries = l2_entries = 0
    entries_source = "none"
    entries_capped = False
    r = get_redis()
    if r is not None:
        try:
            l1_entries, c1 = _scan_count(r, "rag:a:*")
            l2_entries, c2 = _scan_count(r, "rag:e:*")
            entries_source = "scan"
            entries_capped = c1 or c2
        except Exception:
            entries_source = "none"
    return {
        "hit": hits,
        "miss": misses,
        "hit_ratio": round(hits / total, 4) if total else 0.0,
        "l1_hit": _stats["l1_hit"],
        "l1_miss": _stats["l1_miss"],
        "l2_hit": _stats["l2_hit"],
        "l2_miss": _stats["l2_miss"],
        # l1_entries/l2_entries = Redis 键基数(SCAN,非 hit 计数)
        "l1_entries": l1_entries,
        "l2_entries": l2_entries,
        "entries_source": entries_source,
        "entries_capped": entries_capped,
        "enabled": rag_cache_enabled(),
        "redis": r is not None,
    }
