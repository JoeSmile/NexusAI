"""Task 45b.5A — category-vertical crawl sources."""

from __future__ import annotations

from packages.content_ops.hotspot_crawl import (
    HOTSPOT_SOURCES,
    crawl_hotspots,
    sources_for_categories,
)


def test_zsb_category_uses_vertical_not_only_homepages() -> None:
    specs = sources_for_categories(["专升本"])
    urls = [s[2] for s in specs]
    assert specs != HOTSPOT_SOURCES
    assert any("eol" in u or "zsb" in u.lower() or "zhuansheng" in u.lower() for u in urls)


def test_unmatched_category_falls_back_to_default_hubs() -> None:
    specs = sources_for_categories(["天文物理"])
    assert specs == list(HOTSPOT_SOURCES)


def test_empty_categories_uses_default() -> None:
    assert sources_for_categories(None) == list(HOTSPOT_SOURCES)
    assert sources_for_categories([]) == list(HOTSPOT_SOURCES)


def test_crawl_hotspots_tags_category_when_vertical(
    monkeypatch,
) -> None:
    html = """
    <html><body>
      <a href="/n/2026/zsb-policy.html">2026年专升本招生政策通知发布</a>
      <a href="/n/other.html">随便看看更多内容导航</a>
    </body></html>
    """
    monkeypatch.setattr(
        "packages.content_ops.hotspot_crawl._fetch_html",
        lambda *_a, **_k: html,
    )
    out = crawl_hotspots(per_source=5, categories=["专升本"])
    titles = " ".join(str(i.get("title") or "") for i in out.get("items") or [])
    assert "专升本" in titles
    cats = {str(i.get("category") or "") for i in (out.get("items") or [])}
    assert "专升本" in cats
