"""Evidence mapping — real sources only."""

from backend.core.workflow.evidence import evidence_from_rag_sources


def test_empty_sources_yield_empty_evidence():
    assert evidence_from_rag_sources([], node_id="n1") == []
    assert evidence_from_rag_sources(None, node_id="n1") == []


def test_sources_map_to_quotes():
    out = evidence_from_rag_sources(
        [{"content": "chunk text", "metadata": {"title": "doc-a"}}],
        node_id="n1",
    )
    assert len(out) == 1
    assert out[0]["kind"] == "quote"
    assert out[0]["title"] == "doc-a"
    assert out[0]["snippet"] == "chunk text"
    assert out[0]["source_node_id"] == "n1"
