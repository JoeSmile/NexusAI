"""Task 29: RAG L1/L2 缓存 — mock redis / openai / LLM,不碰真服务。"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.core.errors import ContextGateException, ErrorCode
from backend.modules.rag import cache as rag_cache


class FakeRedis:
    """最小同步 redis 替身(decode_responses=False 语义)。"""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str | bytes):
        k = key.decode() if isinstance(key, bytes) else key
        return self.store.get(k)

    def setex(self, key: str, ttl: int, value) -> bool:
        k = key if isinstance(key, str) else key.decode()
        if isinstance(value, str):
            value = value.encode("utf-8")
        self.store[k] = value
        return True

    def set(self, key: str, value, nx: bool = False, ex: int | None = None):
        k = key if isinstance(key, str) else key.decode()
        if nx and k in self.store:
            return False
        if isinstance(value, str):
            value = value.encode("utf-8")
        self.store[k] = value
        return True

    def incr(self, key: str) -> int:
        k = key if isinstance(key, str) else key.decode()
        raw = self.store.get(k)
        n = int(raw.decode() if isinstance(raw, bytes) else raw or 0) + 1
        self.store[k] = str(n).encode("utf-8")
        return n

    def expire(self, key: str, ttl: int) -> bool:
        return True

    def delete(self, key: str) -> int:
        k = key if isinstance(key, str) else key.decode()
        return 1 if self.store.pop(k, None) is not None else 0

    def scan(self, cursor=0, match=None, count=100):
        import fnmatch

        keys = list(self.store.keys())
        if match:
            keys = [k for k in keys if fnmatch.fnmatch(k, match)]
        return 0, keys


@pytest.fixture
def fake_redis(monkeypatch):
    rag_cache.reset_redis_for_tests()
    fr = FakeRedis()
    monkeypatch.setenv("RAG_CACHE_ENABLED", "true")
    monkeypatch.setattr(rag_cache, "_redis", fr)
    monkeypatch.setattr(rag_cache, "_redis_failed", False)

    def _get():
        return fr

    monkeypatch.setattr(rag_cache, "get_redis", _get)
    yield fr
    rag_cache.reset_redis_for_tests()


def test_normalize_nfkc_case_whitespace():
    assert rag_cache.normalize("ＡＢＣ") == "abc"
    assert rag_cache.normalize("Hello   World") == "hello world"
    assert rag_cache.normalize("  信息安全  ") == "信息安全"
    assert rag_cache.normalize("Foo\t\nBar") == "foo bar"


def test_l2_same_text_one_api_call(fake_redis, monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")

    calls = {"n": 0}
    vec768 = [0.01 * i for i in range(768)]

    class _Emb:
        def create(self, **kwargs):
            calls["n"] += 1
            return SimpleNamespace(data=[SimpleNamespace(embedding=list(vec768))])

    class _Client:
        def __init__(self, *a, **k):
            self.embeddings = _Emb()

    monkeypatch.setattr("openai.OpenAI", _Client)

    from backend.database import embeddings as emb_mod
    from backend.database.embeddings import embed_text, reset_embed_mode_for_tests

    reset_embed_mode_for_tests()
    spec = SimpleNamespace(
        name="text-embedding-v3",
        base_url="https://example.test/v1",
        api_key_ref="QWEN_API_KEY",
    )
    monkeypatch.setattr(
        "backend.core.model_registry.select_embedding_model",
        lambda: spec,
    )
    a = embed_text("Hello World")
    b = embed_text("hello   world")
    assert calls["n"] == 1
    assert len(a) == 1536
    assert a[:768] == pytest.approx(b[:768])
    assert emb_mod._last_embed_mode == "api"


def test_l2_model_key_isolation(fake_redis):
    v1 = [1.0] * 768
    v2 = [2.0] * 768
    rag_cache.l2_set("model-a", "q", v1)
    rag_cache.l2_set("model-b", "q", v2)
    assert rag_cache.l2_get("model-a", "q")[0] == pytest.approx(1.0)
    assert rag_cache.l2_get("model-b", "q")[0] == pytest.approx(2.0)


def _make_rag_service(llm_invoke, retrieve_docs=None):
    from langchain_core.prompts import PromptTemplate

    from backend.modules.rag.services.rag_service import RAGService

    svc = RAGService.__new__(RAGService)
    svc.kb_manager = MagicMock()
    svc.llm = MagicMock()
    svc.llm.invoke = llm_invoke
    svc.prompt_template = PromptTemplate(
        template="ctx:{context}\nq:{question}\n",
        input_variables=["context", "question"],
    )
    docs = retrieve_docs or [
        SimpleNamespace(page_content="知识A", metadata={"source": "a"})
    ]

    def _retrieve(question, search_k=3):
        return docs

    svc.retrieve_documents = _retrieve  # type: ignore[method-assign]
    return svc


def test_l1_ask_second_hit(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda *a, **k: None
    )
    calls = {"n": 0}

    def invoke(prompt):
        calls["n"] += 1
        return SimpleNamespace(content="答案")

    svc = _make_rag_service(invoke)
    r1 = svc.ask("如何查询制度？", tenant_id="t1", user_id="u1")
    r2 = svc.ask("如何查询制度？", tenant_id="t1", user_id="u1")
    assert r1["cache_hit"] is False
    assert r2["cache_hit"] is True
    assert calls["n"] == 1
    assert r2["answer"] == "答案"


def test_epoch_invalidates_l1(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda *a, **k: None
    )
    calls = {"n": 0}

    def invoke(prompt):
        calls["n"] += 1
        return SimpleNamespace(content=f"v{calls['n']}")

    svc = _make_rag_service(invoke)
    svc.ask("同一问题", tenant_id="t1")
    assert calls["n"] == 1
    rag_cache.bump_epoch("t1")
    r = svc.ask("同一问题", tenant_id="t1")
    assert r["cache_hit"] is False
    assert calls["n"] == 2


def test_single_flight_one_llm(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda *a, **k: None
    )
    calls = {"n": 0}
    barrier = threading.Barrier(2)

    def invoke(prompt):
        calls["n"] += 1
        time.sleep(0.25)
        return SimpleNamespace(content="shared")

    svc = _make_rag_service(invoke)
    results: list[dict] = []

    def worker():
        barrier.wait()
        results.append(svc.ask("并发问题", tenant_id="t1"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert calls["n"] == 1
    assert any(r.get("cache_hit") for r in results)


def test_rate_limit_miss(fake_redis, monkeypatch):
    monkeypatch.setenv("RAG_RATE_LIMIT_MISS", "2")
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda *a, **k: None
    )

    def invoke(prompt):
        return SimpleNamespace(content="x")

    # 强制每次 L1 miss:每次 bump epoch
    svc = _make_rag_service(invoke)
    with pytest.raises(ContextGateException) as ei:
        for i in range(5):
            rag_cache.bump_epoch("t-rl")
            # 清掉可能的命中
            svc.ask(f"q-{i}-unique-{i}", tenant_id="t-rl")
    assert ei.value.code == ErrorCode.RATE_LIMITED.value


def test_redis_down_silent_degrade(monkeypatch):
    rag_cache.reset_redis_for_tests()
    monkeypatch.setenv("RAG_CACHE_ENABLED", "true")
    monkeypatch.setattr(rag_cache, "_redis_failed", True)
    monkeypatch.setattr(rag_cache, "_redis", None)
    monkeypatch.setattr(rag_cache, "get_redis", lambda: None)
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda *a, **k: None
    )

    def invoke(prompt):
        return SimpleNamespace(content="ok")

    svc = _make_rag_service(invoke)
    r = svc.ask("降级问题", tenant_id="t1")
    assert r["answer"] == "ok"
    assert r["cache_hit"] is False


def test_cache_stats_entries_from_scan(fake_redis):
    rag_cache.l2_set("m", "q1", [0.1] * 768)
    rag_cache.l2_set("m", "q2", [0.2] * 768)
    rag_cache.l1_set("t1", "问题一", {"answer": "a", "sources": []})
    snap = rag_cache.cache_stats_snapshot()
    assert snap["entries_source"] == "scan"
    assert snap["l2_entries"] == 2
    assert snap["l1_entries"] == 1
    assert snap["entries_capped"] is False


def test_pii_skips_l1_cache(fake_redis, monkeypatch):
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda *a, **k: None
    )
    calls = {"n": 0}

    def invoke(prompt):
        calls["n"] += 1
        return SimpleNamespace(content="pii-ans")

    svc = _make_rag_service(invoke)
    q = "我的身份证是110101199001011234请查制度"
    r1 = svc.ask(q, tenant_id="t1")
    r2 = svc.ask(q, tenant_id="t1")
    assert r1["cache_hit"] is False
    assert r2["cache_hit"] is False
    assert calls["n"] == 2
    # redis 不应有 L1 答案 key
    assert not any(k.startswith("rag:a:") for k in fake_redis.store)


def test_miss_audit_carries_real_cost(fake_redis, monkeypatch):
    """miss 审计 cost 必须 = LLM 成本 + embedding 成本,不得硬编码 0(Task 29 review)。"""
    records: list[dict] = []
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda rec: records.append(rec)
    )

    def invoke(prompt):
        return SimpleNamespace(content="答案", metadata={"cost": 0.00042})

    svc = _make_rag_service(invoke)
    r = svc.ask("如何查询制度？", tenant_id="t1", user_id="u1")
    assert r["cache_hit"] is False
    assert records, "miss 路径应写审计"
    cost = records[-1]["cost"]
    assert cost >= 0.00042, f"审计 cost 应含 LLM 成本,实际 {cost}"
    assert cost > 0.00042, "L2 miss 时还应计入 embedding 成本"


def test_embedding_cost_zero_on_l2_hit(fake_redis, monkeypatch):
    """L2 命中时 embedding 成本为 0(不重复计费)。"""
    from backend.core.model_registry import select_embedding_model

    spec = select_embedding_model()
    rag_cache.l2_set(spec.name, rag_cache.normalize("缓存命中问题"), [0.1] * 768)

    records: list[dict] = []
    monkeypatch.setattr(
        "backend.core.audit.write_audit_sync", lambda rec: records.append(rec)
    )

    def invoke(prompt):
        return SimpleNamespace(content="答案", metadata={"cost": 0.00042})

    svc = _make_rag_service(invoke)
    # 直接验证预估函数:L2 已命中 → 0
    est = svc._embedding_cost_if_miss(rag_cache.normalize("缓存命中问题"))
    assert est == 0.0
    # 全链路:L2 命中 + L1 miss → 审计 cost 只含 LLM
    r = svc.ask("缓存命中问题", tenant_id="t1")
    assert r["cache_hit"] is False
    assert records[-1]["cost"] == pytest.approx(0.00042)
