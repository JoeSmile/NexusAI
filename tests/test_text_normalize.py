"""Task 39.01: shared normalize / query_hash."""

from __future__ import annotations

from backend.core.text_normalize import make_normalized_query_hash, normalize_text
from packages.rag import cache as rag_cache


def test_normalize_whitespace_variants_same_hash():
    a = make_normalized_query_hash("你好")
    b = make_normalized_query_hash("你好 ")
    c = make_normalized_query_hash("你好\u3000")  # ideographic space
    assert a == b == c
    assert len(a) == 16


def test_normalize_nfkc_lower_fold():
    assert normalize_text("ＡＢＣ") == "abc"
    assert normalize_text("Hello   World") == "hello world"
    assert normalize_text("  信息安全  ") == "信息安全"
    assert normalize_text("Foo\t\nBar") == "foo bar"
    assert normalize_text("") == ""


def test_rag_reexport_byte_identical():
    samples = ["你好 ", "ＡＢＣ", "Hello   World", "Foo\t\nBar", ""]
    for s in samples:
        assert rag_cache.normalize(s) == normalize_text(s)
        assert rag_cache.norm_hash(s) == make_normalized_query_hash(s)
