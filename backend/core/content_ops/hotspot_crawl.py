"""Hotspot dig — crawl Tier-1/2 education news hubs (no LLM).

Default sources (5 each → merge + dedupe):
1. 教育部新闻 https://www.moe.gov.cn/jyb_xwfb/
2. 中国教育在线 https://www.eol.cn/
3. 研招网 https://yz.chsi.com.cn/
4. 央视网教育 https://edu.cctv.com/
5. 人民网教育 http://edu.people.com.cn/
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (compatible; NexusAI-HotspotDig/1.0; +https://localhost)"
)
_TIMEOUT = 12
_PER_SOURCE = 5

SourceSpec = tuple[str, str, str, Callable[[BeautifulSoup, str], list[dict[str, Any]]]]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    return s


def _clean_text(s: str, *, max_len: int = 200) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s[:max_len]


def _abs_url(base: str, href: str) -> str:
    return urljoin(base, href.strip())


def _looks_like_article(href: str, title: str) -> bool:
    if not href or not title:
        return False
    if len(title) < 8 or len(title) > 120:
        return False
    low = href.lower()
    if low.startswith("javascript:") or low.startswith("#"):
        return False
    skip_bits = (
        "login",
        "register",
        "about",
        "sitemap",
        "mailto:",
        "weibo",
        "download",
    )
    if any(b in low for b in skip_bits):
        return False
    # 过短导航词
    nav = {"首页", "更多", "查看更多", "下一页", "上一页", "返回", "登录", "注册"}
    if title in nav:
        return False
    return True


def _collect_anchors(
    soup: BeautifulSoup,
    base: str,
    *,
    limit: int,
    path_hint: str | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in soup.find_all("a", href=True):
        title = _clean_text(a.get_text(" ", strip=True), max_len=100)
        href = str(a.get("href") or "")
        url = _abs_url(base, href)
        if not _looks_like_article(url, title):
            continue
        if path_hint and path_hint not in url and path_hint not in href:
            # soft filter — still allow if title looks newsy
            if not re.search(r"\d{4}|通知|办法|政策|高考|中考|研|职教|义务教育", title):
                continue
        key = title
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": title,
                "summary": "",
                "url": url,
            }
        )
        if len(out) >= limit:
            break
    return out


def _parse_moe(soup: BeautifulSoup, base: str) -> list[dict[str, Any]]:
    # 新闻列表多在 li > a
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = str(a.get("href") or "")
        title = _clean_text(a.get_text(" ", strip=True), max_len=100)
        url = _abs_url(base, href)
        if "moe.gov.cn" not in urlparse(url).netloc:
            continue
        if not _looks_like_article(url, title):
            continue
        # 优先带日期路径或 xwfb 下详情
        if not re.search(r"/\d{4}/\d{2}|t\d+|shtml|htm", url) and "xwfb" not in url:
            if len(title) < 12:
                continue
        if title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "summary": "教育部官网新闻/政策动态", "url": url})
        if len(items) >= _PER_SOURCE:
            break
    if len(items) < _PER_SOURCE:
        items.extend(
            x
            for x in _collect_anchors(soup, base, limit=_PER_SOURCE)
            if x["title"] not in seen
        )
    return items[:_PER_SOURCE]


def _parse_eol(soup: BeautifulSoup, base: str) -> list[dict[str, Any]]:
    items = _collect_anchors(soup, base, limit=_PER_SOURCE * 3)
    edu = []
    for it in items:
        t = it["title"]
        if re.search(
            r"教育|高考|中考|研|职教|高校|学校|招生|志愿|留学|双减|分流",
            t,
        ):
            it["summary"] = "中国教育在线 · 行业资讯"
            edu.append(it)
        if len(edu) >= _PER_SOURCE:
            break
    return (edu or items)[:_PER_SOURCE]


def _parse_chsi(soup: BeautifulSoup, base: str) -> list[dict[str, Any]]:
    items = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        title = _clean_text(a.get_text(" ", strip=True), max_len=100)
        href = str(a.get("href") or "")
        url = _abs_url(base, href)
        if "chsi.com.cn" not in urlparse(url).netloc:
            continue
        if not _looks_like_article(url, title):
            continue
        if not re.search(r"研|硕士|博士|招生|调剂|推免|政策|分数", title):
            continue
        if title in seen:
            continue
        seen.add(title)
        items.append(
            {"title": title, "summary": "研招网 · 考研招生政策/资讯", "url": url}
        )
        if len(items) >= _PER_SOURCE:
            break
    if len(items) < 2:
        items = _collect_anchors(soup, base, limit=_PER_SOURCE)
        for it in items:
            it["summary"] = "研招网 · 页面条目"
    return items[:_PER_SOURCE]


def _parse_cctv_edu(soup: BeautifulSoup, base: str) -> list[dict[str, Any]]:
    items = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        title = _clean_text(a.get_text(" ", strip=True), max_len=100)
        href = str(a.get("href") or "")
        url = _abs_url(base, href)
        if "cctv.com" not in urlparse(url).netloc:
            continue
        if not _looks_like_article(url, title):
            continue
        if title in seen:
            continue
        seen.add(title)
        items.append(
            {"title": title, "summary": "央视网教育 · 权威报道", "url": url}
        )
        if len(items) >= _PER_SOURCE:
            break
    return items[:_PER_SOURCE]


def _parse_people_edu(soup: BeautifulSoup, base: str) -> list[dict[str, Any]]:
    items = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        title = _clean_text(a.get_text(" ", strip=True), max_len=100)
        href = str(a.get("href") or "")
        url = _abs_url(base, href)
        host = urlparse(url).netloc
        if "people.com.cn" not in host and "people.cn" not in host:
            continue
        if not _looks_like_article(url, title):
            continue
        if title in seen:
            continue
        seen.add(title)
        items.append(
            {"title": title, "summary": "人民网教育 · 权威报道", "url": url}
        )
        if len(items) >= _PER_SOURCE:
            break
    return items[:_PER_SOURCE]


HOTSPOT_SOURCES: list[SourceSpec] = [
    (
        "moe",
        "教育部官网",
        "https://www.moe.gov.cn/jyb_xwfb/",
        _parse_moe,
    ),
    (
        "eol",
        "中国教育在线",
        "https://www.eol.cn/",
        _parse_eol,
    ),
    (
        "chsi",
        "研招网",
        "https://yz.chsi.com.cn/",
        _parse_chsi,
    ),
    (
        "cctv_edu",
        "央视网教育",
        "https://edu.cctv.com/",
        _parse_cctv_edu,
    ),
    (
        "people_edu",
        "人民网教育",
        "http://edu.people.com.cn/",
        _parse_people_edu,
    ),
]


def _fetch_html(session: requests.Session, url: str) -> str | None:
    try:
        r = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            logger.warning("hotspot crawl HTTP %s for %s", r.status_code, url)
            return None
        r.encoding = r.apparent_encoding or r.encoding or "utf-8"
        return r.text
    except requests.RequestException as e:
        logger.warning("hotspot crawl failed %s: %s", url, e)
        return None


def crawl_source(
    session: requests.Session,
    source_id: str,
    source_name: str,
    url: str,
    parser: Callable[[BeautifulSoup, str], list[dict[str, Any]]],
    *,
    per_source: int = _PER_SOURCE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {
        "source_id": source_id,
        "source_name": source_name,
        "url": url,
        "ok": False,
        "count": 0,
        "error": None,
    }
    html = _fetch_html(session, url)
    if not html:
        meta["error"] = "fetch_failed"
        return [], meta
    try:
        soup = BeautifulSoup(html, "html.parser")
        raw_items = parser(soup, url)[:per_source]
    except Exception as e:  # noqa: BLE001 — isolate per-source parse
        logger.exception("hotspot parse failed %s", source_id)
        meta["error"] = f"parse_failed:{e}"
        return [], meta

    out: list[dict[str, Any]] = []
    for i, it in enumerate(raw_items):
        title = _clean_text(str(it.get("title") or ""), max_len=200)
        if not title:
            continue
        link = str(it.get("url") or url)
        summary = _clean_text(str(it.get("summary") or ""), max_len=800)
        # 原文摘录：短文（<50 字）整段保留；勿用「站点名 · 栏目」类占位摘要冒充原文
        stub = (
            not summary
            or summary.startswith(source_name)
            or summary.startswith(f"来自{source_name}")
            or (len(summary) < 40 and "·" in summary)
        )
        if stub:
            excerpt_src = title
        elif title and title not in summary:
            excerpt_src = f"{title} — {summary}"
        else:
            excerpt_src = summary or title
        if len(excerpt_src) < 50:
            excerpt = excerpt_src  # 少于 50 字整段写入，不截断
        else:
            excerpt = excerpt_src[:800]
        out.append(
            {
                "title": title[:120],
                "summary": summary or f"来自{source_name}",
                "category": "教育资讯",
                "score": max(60, 95 - i * 3),
                "source": source_name,
                "reference_material_links": [link],
                "evidence": {
                    "source_kind": "web_crawl",
                    "source_label": source_name,
                    "source_url": link,
                    "list_url": url,
                    "raw_excerpt": excerpt,
                    # 有条目链接时不再写「列表页抓取自…」说明（前端展示参考链接即可）
                },
            }
        )
    meta["ok"] = True
    meta["count"] = len(out)
    return out, meta


def crawl_hotspots(
    *,
    per_source: int = _PER_SOURCE,
    sources: list[SourceSpec] | None = None,
) -> dict[str, Any]:
    """Crawl configured hubs; return items + per-source crawl report."""
    specs = sources or HOTSPOT_SOURCES
    session = _session()
    all_items: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for source_id, source_name, url, parser in specs:
        items, meta = crawl_source(
            session,
            source_id,
            source_name,
            url,
            parser,
            per_source=per_source,
        )
        reports.append(meta)
        all_items.extend(items)

    # 去重：标题 token 集相同则保留更高分 / 先到
    from backend.core.content_ops.hotspot import (
        item_hot_score,
        normalize_title_token_set,
    )

    deduped: list[dict[str, Any]] = []
    index: dict[frozenset[str], int] = {}
    skipped = 0
    for it in all_items:
        key = normalize_title_token_set(str(it.get("title") or ""))
        if key and key in index:
            skipped += 1
            i = index[key]
            if item_hot_score(it) > item_hot_score(deduped[i]):
                deduped[i] = it
            continue
        if key:
            index[key] = len(deduped)
        deduped.append(it)

    deduped.sort(key=lambda x: -item_hot_score(x))
    return {
        "items": deduped,
        "raw_count": len(all_items),
        "deduped_count": len(deduped),
        "skipped_duplicates": skipped,
        "per_source": per_source,
        "source_reports": reports,
    }
