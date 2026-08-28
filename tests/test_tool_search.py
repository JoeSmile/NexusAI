"""Task 60 — hybrid tool search (BM25 + vector RRF + fallback)."""

from __future__ import annotations

import pytest

from packages.tool_search import search as search_mod
from packages.tool_search.bm25 import BM25Index
from packages.tool_search.rrf import reciprocal_rank_fusion
from packages.tool_search.search import ToolSearchIndex, search_tools_hybrid
from packages.tool_search.vector_index import LocalToolEmbedder, VectorToolIndex


@pytest.fixture(autouse=True)
def _reset_global_index() -> None:
    search_mod._INDEX = None
    yield
    search_mod._INDEX = None


def _caps() -> list[dict]:
    return [
        {
            "id": "skill:weather",
            "name": "天气查询",
            "kind": "skill",
            "description": "查询城市天气预报与温度",
            "tags": ["weather"],
        },
        {
            "id": "skill:translate",
            "name": "翻译助手",
            "kind": "skill",
            "description": "多语言文本翻译",
            "tags": ["nlp"],
        },
        {
            "id": "agent:research",
            "name": "研究助手",
            "kind": "agent",
            "description": "检索资料并撰写摘要",
            "tags": [],
        },
        {
            "id": "model:chat",
            "name": "通用对话",
            "kind": "model",
            "description": "基础聊天模型",
            "tags": [],
        },
    ]


def test_bm25_finds_lexical_overlap() -> None:
    idx = BM25Index()
    idx.upsert("a", "天气预报 北京 温度")
    idx.upsert("b", "股票行情 涨跌")
    hits = idx.search("北京天气", top_k=2)
    assert hits
    assert hits[0][0] == "a"


def test_rrf_merges_two_lists() -> None:
    merged = reciprocal_rank_fusion(
        [["a", "b", "c"], ["c", "d", "a"]],
        limit=3,
    )
    assert merged[0] == "a"
    assert "c" in merged


def test_zero_recall_fallback_never_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_SEARCH_HYBRID_ENABLED", "1")
    caps = _caps()
    # Query with no token overlap — should still return >=2 via fallback
    out = search_tools_hybrid(caps, "xyzqwerty unrelated tokens", top_k=12, stable_threshold=3)
    assert len(out) >= 2


def test_stable_small_catalog_full_expose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_SEARCH_HYBRID_ENABLED", "1")
    caps = _caps()[:2]
    out = search_tools_hybrid(caps, "anything", stable_threshold=10)
    assert len(out) == 2


def test_vector_index_search_with_hash_embedder() -> None:
    embedder = LocalToolEmbedder()
    embedder._load_attempted = True
    embedder._model = None
    embedder._mode = "hash"
    vidx = VectorToolIndex(embedder=embedder)
    vidx.upsert("x", "alpha beta gamma")
    vidx.upsert("y", "delta epsilon")
    hits = vidx.search("alpha", top_k=1)
    assert hits
    assert hits[0][0] == "x"


def test_tool_search_index_respects_allowed_ids() -> None:
    idx = ToolSearchIndex()
    for cap in _caps():
        idx.upsert_cap(cap)
    hits = idx.search("天气", allowed_ids={"skill:weather"}, top_k=5)
    assert hits
    assert all(h["id"] == "skill:weather" for h in hits)
