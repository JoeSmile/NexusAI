"""Hotspot dig — manual activation; topic_agent / paste / seed."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Literal

logger = logging.getLogger(__name__)

AdapterName = Literal["topic_agent", "paste", "seed"]


class HotspotCrawlError(RuntimeError):
    """Web crawl returned no items (no seed fallback)."""

    def __init__(self, message: str, *, crawl_meta: dict[str, Any] | None = None):
        super().__init__(message)
        self.crawl_meta = crawl_meta or {}

# 教培常用方向（表单多选；也作 seed category）
EDU_DIRECTIONS: tuple[str, ...] = (
    "专升本",
    "考研",
    "博士",
    "海外留学",
    "中外合作办学",
    "在职研究生",
    "MBA",
)

_SEED_HOTSPOTS: list[dict[str, Any]] = [
    {
        "title": "2026统招专升本:扩招还是收紧,专科生要不要冲",
        "summary": "报名人数、招生计划与专业限制变化,数据以各省考试院官方为准",
        "category": "专升本",
        "score": 92,
    },
    {
        "title": "专升本选专业:哪些专业上岸率高、就业不吃亏",
        "summary": "结合录取率与就业方向理性分析,不承诺上岸",
        "category": "专升本",
        "score": 86,
    },
    {
        "title": "专科考编考公:学历门槛到底卡在哪",
        "summary": "职位表学历要求逐条解读,专科生的可报考路径盘点",
        "category": "专升本",
        "score": 82,
    },
    {
        "title": "2026考研报名人数:考研降温了吗,理性择校三件事",
        "summary": "报录比、复试线、压分怎么甄别,择校不只看分数线",
        "category": "考研",
        "score": 90,
    },
    {
        "title": "在职考研:下班后怎么安排复习,3个可行方案",
        "summary": "时间管理、科目取舍、精力分配,给在职考生可执行的路径",
        "category": "考研",
        "score": 85,
    },
    {
        "title": "考研调剂与二战:别让一次失利定义你",
        "summary": "调剂流程梳理、二战决策的理性评估,不贩卖焦虑",
        "category": "考研",
        "score": 80,
    },
    {
        "title": "申博条件拆解:论文、导师、背景,哪块最关键",
        "summary": "以目标院校招生简章为准,分学科讲清申请权重",
        "category": "博士",
        "score": 84,
    },
    {
        "title": "读博值不值:就业、收入、机会成本算笔账",
        "summary": "分学科理性对比,不神化不劝退",
        "category": "博士",
        "score": 78,
    },
    {
        "title": "留学费用大起底:热门国家一年真实花费",
        "summary": "学费与生活费按官方及公开数据整理,量入为出",
        "category": "海外留学",
        "score": 88,
    },
    {
        "title": "留学回国就业:学历认证、落户、考公怎么用",
        "summary": "留服认证流程、落户与考公政策,以官方文件为准",
        "category": "海外留学",
        "score": 83,
    },
    {
        "title": "中外合作办学值不值:教育部认证名单怎么查",
        "summary": "教育部涉外监管信息网查询路径,识别正规项目",
        "category": "中外合作办学",
        "score": 87,
    },
    {
        "title": "不出国也能拿海外学位?合作办学含金量真相",
        "summary": "分辨正规项目与野鸡项目,学历认证口径解读",
        "category": "中外合作办学",
        "score": 81,
    },
    {
        "title": "非全日制研究生含金量:和全日制差在哪",
        "summary": "报考、就业、考公认可度逐项对比,按个人情况选择",
        "category": "在职研究生",
        "score": 86,
    },
    {
        "title": "同等学力申硕:单证还是双证,适合谁",
        "summary": "申请条件与流程梳理,讲清适合的人群",
        "category": "在职研究生",
        "score": 79,
    },
    {
        "title": "MBA报考条件:工作年限怎么算,谁能报",
        "summary": "院校官方要求逐条解读,评估自身资格",
        "category": "MBA",
        "score": 85,
    },
    {
        "title": "MBA学费这么贵值吗:职业价值算笔账",
        "summary": "从晋升、转型、人脉视角理性评估投入产出",
        "category": "MBA",
        "score": 82,
    },
]



def item_hot_score(it: dict[str, Any]) -> int:
    """Prefer hot_score; fall back to legacy score."""
    for k in ("hot_score", "score"):
        if k not in it or it.get(k) is None or it.get(k) == "":
            continue
        try:
            return int(it[k])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return 0


def content_hash(items: list[dict[str, Any]]) -> str:
    payload = json.dumps(items, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


_STOP_CHARS = frozenset("的了与和及啊呢吗吧")


def normalize_title_token_set(title: str) -> frozenset[str]:
    """45b: 去空格/标点/轻停用 → 字/词 token 集（同集 = 重复，含词序颠倒）。"""
    s = (title or "").strip().lower()
    s = re.sub(
        r"[\s\-_/|·•，。、；：！？!?,.\"'“”‘’「」『』【】（）()\[\]《》…]+",
        "",
        s,
    )
    tokens: set[str] = set()
    for m in re.finditer(r"[a-z0-9]+", s):
        tokens.add(m.group())
    for ch in s:
        if "\u4e00" <= ch <= "\u9fff" and ch not in _STOP_CHARS:
            tokens.add(ch)
    return frozenset(tokens)


def token_jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def titles_are_duplicate(a: str, b: str) -> bool:
    return normalize_title_token_set(a) == normalize_title_token_set(b)


def annotate_similar_to_previous(
    items: list[dict[str, Any]],
    previous: list[dict[str, Any]] | None,
    *,
    jaccard_threshold: float = 0.9,
) -> list[dict[str, Any]]:
    """Mark items similar to recent pool; never drop them (45b 展示层近似)."""
    prev_sets = [
        normalize_title_token_set(str(p.get("title") or ""))
        for p in (previous or [])
        if p.get("title")
    ]
    out: list[dict[str, Any]] = []
    for it in items:
        row = dict(it)
        ts = normalize_title_token_set(str(row.get("title") or ""))
        similar = False
        for ps in prev_sets:
            if not ts:
                break
            if ts == ps or token_jaccard(ts, ps) >= jaccard_threshold:
                similar = True
                break
        row["similar_to_previous"] = similar
        out.append(row)
    return out


def merge_hotspot_pool(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Dedupe by normalize token set; keep higher score. Returns pool, new, skipped."""
    pool: list[dict[str, Any]] = []
    index: dict[frozenset[str], int] = {}
    for it in existing:
        row = {k: v for k, v in dict(it).items() if k != "similar_to_previous"}
        key = normalize_title_token_set(str(row.get("title") or ""))
        if not key:
            pool.append(row)
            continue
        if key in index:
            i = index[key]
            if item_hot_score(row) > item_hot_score(pool[i]):
                pool[i] = row
        else:
            index[key] = len(pool)
            pool.append(row)

    new_count = 0
    skipped = 0
    for it in incoming:
        row = {k: v for k, v in dict(it).items() if k != "similar_to_previous"}
        key = normalize_title_token_set(str(row.get("title") or ""))
        if key and key in index:
            skipped += 1
            i = index[key]
            if item_hot_score(row) > item_hot_score(pool[i]):
                pool[i] = row
            continue
        new_count += 1
        if key:
            index[key] = len(pool)
        pool.append(row)

    pool.sort(key=lambda x: -item_hot_score(x))
    return pool, new_count, skipped


def _split_keywords(raw: str | None) -> list[str]:
    return [k.strip() for k in re.split(r"[,，\s]+", raw or "") if k.strip()]


def _filter_items(
    items: list[dict[str, Any]],
    *,
    categories: list[str] | None,
    keywords: str | None,
    exclude_keywords: str | None = None,
) -> list[dict[str, Any]]:
    cats = {c.strip() for c in (categories or []) if c and str(c).strip()}
    kws = _split_keywords(keywords)
    excl = _split_keywords(exclude_keywords)
    out: list[dict[str, Any]] = []
    for it in items:
        if cats and str(it.get("category") or "") not in cats:
            continue
        blob = f"{it.get('title', '')} {it.get('summary', '')}"
        if excl and any(k in blob for k in excl):
            continue
        if kws and not any(k in blob for k in kws):
            continue
        out.append(dict(it))
    return out


def _parse_paste(text: str) -> list[dict[str, Any]]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    items: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        ln2 = re.sub(r"^\d+[\.\)、]\s*", "", ln)
        if "—" in ln2 or " - " in ln2:
            parts = re.split(r"\s*[—\-]\s*", ln2, maxsplit=1)
            title, summary = parts[0], (parts[1] if len(parts) > 1 else "")
        else:
            title, summary = ln2, ""
        items.append(
            {
                "title": title[:200],
                "summary": summary[:500],
                "category": "粘贴",
                "score": max(50, 100 - i),
                "source": "用户粘贴",
                "evidence": {
                    "source_kind": "paste_line",
                    "source_label": "用户粘贴",
                    "raw_excerpt": ln[:800],
                    "crawl_note": "用户粘贴原文行（未改写）",
                },
            }
        )
    return items


def _sanitize_text(raw: str | None, *, max_len: int) -> str:
    """Strip control chars / trim; dig 入口轻量消毒（非 LLM 护栏替代）。"""
    s = (raw or "").replace("\x00", "")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    return s.strip()[:max_len]


def _note_tokens(note: str) -> list[str]:
    """Extract short phrases from dig-only user note for ranking (never returned as content)."""
    parts = re.split(r"[,，;；。！？、\s]+", note or "")
    out: list[str] = []
    for p in parts:
        t = p.strip()
        if len(t) >= 2:
            out.append(t[:40])
        if len(out) >= 24:
            break
    return out


def _rank_items_by_note(
    items: list[dict[str, Any]], note: str | None
) -> list[dict[str, Any]]:
    """Boost titles/summaries that match note tokens. Note text itself is never written into items."""
    tokens = _note_tokens(note or "")
    if not tokens or not items:
        return items
    scored: list[tuple[int, dict[str, Any]]] = []
    for it in items:
        blob = f"{it.get('title', '')} {it.get('summary', '')}"
        hit = sum(1 for t in tokens if t in blob)
        base = int(it.get("score") or 0)
        scored.append((base + hit * 8, dict(it)))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get("score") or 0)))
    return [it for _, it in scored]


def _topic_agent_items(
    *,
    org_profile: dict[str, Any],
    categories: list[str] | None,
    keywords: str | None,
    exclude_keywords: str | None,
    region: str | None,
    user_note: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Crawl Tier-1/2 hubs (5×5) then dedupe. Empty crawl = fail (no seed fallback).

    ``user_note`` only re-ranks candidates; never written into title/summary.
    Returns (items, crawl_meta).
    """
    del org_profile, categories, region  # reserved for future ranking filters
    crawl_meta: dict[str, Any] = {"mode": "web_crawl", "ok": False}
    try:
        from packages.content_ops.hotspot_crawl import crawl_hotspots

        crawled = crawl_hotspots(per_source=5)
        crawl_meta = {
            "mode": "web_crawl",
            "ok": bool(crawled.get("items")),
            "raw_count": crawled.get("raw_count"),
            "deduped_count": crawled.get("deduped_count"),
            "skipped_duplicates": crawled.get("skipped_duplicates"),
            "source_reports": crawled.get("source_reports"),
            "per_source": crawled.get("per_source"),
        }
        base = list(crawled.get("items") or [])
    except Exception as e:  # noqa: BLE001
        logger.exception("hotspot web crawl failed")
        crawl_meta = {
            "mode": "web_crawl",
            "ok": False,
            "error": f"crawl_exception:{type(e).__name__}",
        }
        raise HotspotCrawlError(
            f"热点抓取失败：外网信源不可用（{type(e).__name__}）",
            crawl_meta=crawl_meta,
        ) from e

    if not base:
        raise HotspotCrawlError(
            "热点抓取失败：五个信源均未拿到可用条目（未回退种子库）",
            crawl_meta=crawl_meta,
        )

    filtered = _filter_items(
        base,
        categories=None,
        keywords=None,
        exclude_keywords=exclude_keywords,
    )
    if not filtered:
        raise HotspotCrawlError(
            "热点抓取失败：抓取结果被排除词滤空（未回退种子库）",
            crawl_meta={**crawl_meta, "filtered_empty": True},
        )
    if keywords:
        kw_tokens = _split_keywords(keywords)

        def _kw_hits(it: dict[str, Any]) -> int:
            blob = f"{it.get('title', '')} {it.get('summary', '')}"
            return sum(1 for k in kw_tokens if k in blob)

        if any(_kw_hits(it) for it in filtered):
            filtered.sort(key=lambda it: (-_kw_hits(it), -item_hot_score(it)))
    return _rank_items_by_note(filtered, user_note), crawl_meta



def _now_str() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _expire_str(days: int = 7) -> str:
    from datetime import datetime, timedelta

    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def normalize_hotspot_item(
    raw: dict[str, Any],
    *,
    rank: int = 1,
    adapter: str = "topic_agent",
    org_profile: dict[str, Any] | None = None,
    dig_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize hotspot record.

    Non-LLM fields are always filled. Fields that need LLM/human research
    (extend_keywords / competition narrative / emotion / full_summary …)
    are only kept when already present on the seed/raw item — never invented.
    """
    import uuid as _uuid

    org = org_profile or {}
    title = str(raw.get("core_topic") or raw.get("title") or "").strip()
    short = str(raw.get("short_desc") or raw.get("summary") or "").strip()
    category = str(raw.get("category") or "素质教育").strip() or "素质教育"
    score = item_hot_score(raw) or 70
    hot_id = str(raw.get("hot_id") or raw.get("id") or _uuid.uuid4())

    source = str(raw.get("source") or "").strip()
    if not source:
        if adapter == "paste" or category == "粘贴":
            source = "用户粘贴"
        else:
            source = "本地种子库（非外网抓取）"

    # —— 证据：始终有中文可读「原文摘录」，不再写「见 raw_excerpt」——
    evidence_in = (
        dict(raw.get("evidence") or {})
        if isinstance(raw.get("evidence"), dict)
        else {}
    )
    raw_excerpt = str(
        evidence_in.get("raw_excerpt")
        or raw.get("原文摘录")
        or short
        or title
        or ""
    ).strip()
    # 少于 50 字整段保留；更长再截到 800
    if len(raw_excerpt) >= 50:
        raw_excerpt = raw_excerpt[:800]
    if adapter == "paste" or category == "粘贴":
        crawl_note = "来源：用户粘贴原文行（未改写）"
        source_kind = "paste_line"
    else:
        crawl_note = (
            "来源：本地教培选题种子库 + 机构画像合成；"
            "当前未接入外网信源爬取。下方「原文摘录」即本条合成依据文本。"
        )
        source_kind = str(
            evidence_in.get("source_kind") or raw.get("source_kind") or "local_seed"
        )
    evidence = {
        **evidence_in,
        "source_kind": source_kind
        if not evidence_in.get("source_kind")
        else evidence_in["source_kind"],
        "source_label": str(evidence_in.get("source_label") or source),
        "raw_excerpt": raw_excerpt,
    }
    # 有参考链接时不展示「列表页抓取自…」类 crawl_note
    refs_preview = raw.get("reference_material_links")
    has_refs = isinstance(refs_preview, list) and any(
        str(x).strip() for x in refs_preview
    )
    inherited_note = str(evidence_in.get("crawl_note") or "").strip()
    if has_refs and (
        inherited_note.startswith("列表页抓取自")
        or "条目链接：" in inherited_note
    ):
        evidence.pop("crawl_note", None)
    elif inherited_note:
        evidence["crawl_note"] = inherited_note
    elif not has_refs:
        evidence["crawl_note"] = crawl_note
    if evidence_in.get("source_url"):
        evidence["source_url"] = evidence_in["source_url"]
    if evidence_in.get("list_url"):
        evidence["list_url"] = evidence_in["list_url"]

    # main_keywords：规则可做（方向 + 用户关键词 + 种子自带）
    main_kw = raw.get("main_keywords")
    if not isinstance(main_kw, list) or not main_kw:
        main_kw = []
        if category and category != "粘贴":
            main_kw.append(category)
        for k in dig_keywords or []:
            if k and k not in main_kw:
                main_kw.append(k)
        # 标题截断作弱关键词（非 LLM）
        if title and title[:10] not in main_kw:
            main_kw.append(title[:16])

    def _list_or_empty(key: str) -> list[str]:
        v = raw.get(key)
        return [str(x) for x in v][:16] if isinstance(v, list) else []

    # —— 以下需 LLM / 人工研究：仅透传种子已有值，缺省为空 ——
    extend_kw = _list_or_empty("extend_keywords")
    exclude_kw = _list_or_empty("exclude_keywords")
    emotion = _list_or_empty("emotion_tag")
    suitable = _list_or_empty("suitable_content_type")
    risk = _list_or_empty("risk_tag")
    competitor = _list_or_empty("competitor_angle")
    refs = _list_or_empty("reference_material_links")
    data_support = _list_or_empty("data_support")

    ta = raw.get("target_audience")
    if isinstance(ta, dict):
        audience = ta
    else:
        # 仅填画像主受众（规则），不做痛点臆造
        primary = str(
            org.get("target_audience") or org.get("targetAudience") or ""
        ).strip()
        audience = {"primary": primary} if primary else {}

    trend = str(raw.get("hot_trend") or "").lower()
    if trend not in ("up", "down", "stable"):
        trend = ""
    competition = str(raw.get("competition_level") or "").lower()
    if competition not in ("high", "medium", "low"):
        competition = ""

    out = {
        **{k: v for k, v in raw.items() if k not in ("evidence",)},
        "hot_id": hot_id,
        "source": source,
        "crawl_time": str(raw.get("crawl_time") or _now_str()),
        "valid_expire_time": str(raw.get("valid_expire_time") or _expire_str(7)),
        "rank": int(raw.get("rank") or rank),
        "hot_score": score,
        "score": score,
        "hot_trend": trend or None,
        "core_topic": title,
        "title": title,
        "short_desc": short,
        "summary": short,
        "full_summary": str(raw.get("full_summary") or "").strip() or None,
        "category": category,
        "main_keywords": [str(x) for x in main_kw][:12],
        "extend_keywords": extend_kw,
        "exclude_keywords": exclude_kw,
        "target_audience": audience,
        "emotion_tag": emotion,
        "content_position": str(raw.get("content_position") or "").strip() or None,
        "suitable_content_type": suitable,
        "competition_level": competition or None,
        "competitor_angle": competitor,
        "differentiate_angle": str(raw.get("differentiate_angle") or "").strip()
        or None,
        "risk_tag": risk,
        "suggest_limit": str(raw.get("suggest_limit") or "").strip() or None,
        "reference_material_links": refs,
        "data_support": data_support,
        "suggested_opening_hook": str(raw.get("suggested_opening_hook") or "").strip()
        or None,
        "evidence": evidence,
        # 顶层中文别名，复制 JSON / 明细里一眼能找到
        "原文摘录": raw_excerpt,
    }
    return out


def enrich_hotspot_items(
    items: list[dict[str, Any]],
    *,
    adapter: str,
    org_profile: dict[str, Any] | None = None,
    dig_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        normalize_hotspot_item(
            it,
            rank=i + 1,
            adapter=adapter,
            org_profile=org_profile,
            dig_keywords=dig_keywords,
        )
        for i, it in enumerate(items)
    ]


def dig_hotspots(
    *,
    adapter: AdapterName = "topic_agent",
    categories: list[str] | None = None,
    keywords: str | None = None,
    exclude_keywords: str | None = None,
    paste_text: str | None = None,
    org_profile: dict[str, Any] | None = None,
    industry: str | None = None,
    region: str | None = None,
    use_org_profile: bool = True,
    user_note: str | None = None,
) -> dict[str, Any]:
    """Return hotspot list + content_hash. Manual trigger only (no cron)."""
    org_profile = dict(org_profile or {}) if use_org_profile else {}
    if industry and str(industry).strip():
        org_profile["industry"] = _sanitize_text(industry, max_len=64)
    if region and str(region).strip():
        org_profile["target_region"] = _sanitize_text(region, max_len=64)

    keywords = _sanitize_text(keywords, max_len=200) or None
    exclude_keywords = _sanitize_text(exclude_keywords, max_len=200) or None
    paste_text = _sanitize_text(paste_text, max_len=8000) or None
    note = _sanitize_text(user_note, max_len=1500) or None
    raw_cats = [
        _sanitize_text(c, max_len=32)
        for c in (categories or [])
        if c and str(c).strip()
    ]
    cats: list[str] | None = raw_cats or None

    # UI 固定智能选题；仍保留 paste/seed 供测试与兼容旧客户端
    adapter_l = str(adapter or "topic_agent").strip().lower()
    crawl_meta: dict[str, Any] | None = None
    if adapter_l == "paste":
        items = _parse_paste(paste_text or "")
        if not items:
            items = _filter_items(
                _SEED_HOTSPOTS,
                categories=cats,
                keywords=keywords,
                exclude_keywords=exclude_keywords,
            )
        else:
            items = _filter_items(
                items,
                categories=None,
                keywords=keywords,
                exclude_keywords=exclude_keywords,
            )
    elif adapter_l == "seed":
        items = _filter_items(
            _SEED_HOTSPOTS,
            categories=cats,
            keywords=keywords,
            exclude_keywords=exclude_keywords,
        )
        if not items:
            items = list(_SEED_HOTSPOTS)
    else:
        items, crawl_meta = _topic_agent_items(
            org_profile=org_profile,
            categories=cats,
            keywords=keywords,
            exclude_keywords=exclude_keywords,
            region=region,
            user_note=note,
        )

    # 5 源 × 5 条去重后通常 ≤25
    items = items[:25]
    items = enrich_hotspot_items(
        items,
        adapter=adapter_l,
        org_profile=org_profile,
        dig_keywords=_split_keywords(keywords) if keywords else None,
    )
    if adapter_l == "paste":
        provenance = "paste：条目来自用户粘贴原文行；详见每条「原文摘录」"
    elif adapter_l == "seed":
        provenance = "seed：本地种子库（仅 adapter=seed 测试路径）"
    else:
        provenance = (
            "web_crawl：教育部 / 教育在线 / 研招网 / 央视教育 / 人民网教育，"
            "各最多 5 条后标题去重；详见 dig_evidence.crawl 与每条原文摘录"
        )
    dig_evidence = {
        "adapter": adapter_l,
        "generated_at": _now_str(),
        "request": {
            "categories": cats,
            "keywords": keywords,
            "exclude_keywords": exclude_keywords,
            "industry": industry,
            "region": region,
            "use_org_profile": use_org_profile,
            "user_note_present": bool(note),
            "user_note_len": len(note or ""),
        },
        "org_profile_snapshot": {
            "industry": org_profile.get("industry"),
            "product_focus": org_profile.get("product_focus")
            or org_profile.get("productFocus"),
            "target_audience": org_profile.get("target_audience")
            or org_profile.get("targetAudience"),
            "target_region": org_profile.get("target_region")
            or org_profile.get("targetRegion"),
        }
        if use_org_profile
        else {},
        "provenance_note": provenance,
        "crawl": crawl_meta,
    }
    return {
        "adapter": adapter_l,
        "items": items,
        "content_hash": content_hash(items),
        "count": len(items),
        "dig_evidence": dig_evidence,
    }


def day_collection_hash(tenant_id: str, day: str) -> str:
    raw = f"hotspot_day:{tenant_id}:{day}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
