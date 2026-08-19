"""Douyin adapter — migrate edu-content-pipeline tikhub_fetch.py stable v2 (Task 52 S1).

Endpoint facts (do not change without re-measure):
- Profile: GET /douyin/web/fetch_user_profile_by_short_id?short_id=
- List: GET /douyin/app/v3/fetch_user_post_videos (app/v3 only; web is partial)
- Detail: POST /douyin/app/v3/fetch_multi_video_v2 body=["id1","id2"] bare array
- play_count always 0 — use digg/collect/share/comment
- Single-page strategy: count=1..50 (caller), max_cursor=0, no pagination loop
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from backend.core.social.http_client import TikHubHttpClient
from backend.core.social.types import AccountInfo, Content, ContentSource, Platform

_DESC_MIN_LEN = 100
_LIST_COUNT_DEFAULT = 20
_LIST_COUNT_MAX = 50
_DETAIL_CHUNK = 50
_DETAIL_SLEEP_S = 1.2


def _find_sec_uid(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "sec_uid" in str(k).lower() and isinstance(v, str) and v:
                return v
            found = _find_sec_uid(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_sec_uid(item)
            if found:
                return found
    return None


def _find_first_str(obj: Any, keys: tuple[str, ...]) -> str | None:
    keyset = {k.lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in keyset and isinstance(v, str) and v.strip():
                return v.strip()
            found = _find_first_str(v, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_str(item, keys)
            if found:
                return found
    return None


def _find_first_int(obj: Any, keys: tuple[str, ...]) -> int | None:
    keyset = {k.lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in keyset and isinstance(v, (int, float)):
                return int(v)
            found = _find_first_int(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_int(item, keys)
            if found is not None:
                return found
    return None


def _find_avatar_url(obj: Any) -> str | None:
    """Prefer avatar_* url_list[0] shapes common in Douyin payloads."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if "avatar" in kl and isinstance(v, dict):
                urls = v.get("url_list") or v.get("urlList")
                if isinstance(urls, list) and urls and isinstance(urls[0], str):
                    return urls[0]
            found = _find_avatar_url(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_avatar_url(item)
            if found:
                return found
    return None


def extract_subtitle_text(v: dict[str, Any]) -> str:
    subs = v.get("subtitle") or []
    if not isinstance(subs, list):
        return ""
    parts: list[str] = []
    for s in subs:
        if isinstance(s, dict):
            txt = s.get("subtitle") or s.get("text") or ""
            if txt:
                parts.append(str(txt))
    return "".join(parts)


def extract_text_and_source(v: dict[str, Any]) -> tuple[str, ContentSource]:
    """Priority: desc ≥100 → caption ≥100 → subtitle (list or detail).

    2026-08-17 实测: Tikhub v3 列表/详情接口的 aweme **无 subtitle 字段**,
    desc 即文案(博主写全文则全文,只写简介则简介)——desc 优先原逻辑恢复。
    """
    desc = (v.get("desc") or "").strip()
    if len(desc) >= _DESC_MIN_LEN:
        return desc, "desc"
    caption = (v.get("caption") or "").strip()
    if len(caption) >= _DESC_MIN_LEN:
        return caption, "caption"
    sub = extract_subtitle_text(v).strip()
    if sub:
        return sub, "subtitle"
    # Short desc still useful as title-layer copy; mark source desc if present
    if desc:
        return desc, "desc"
    if caption:
        return caption, "caption"
    return "", ""


def _aweme_to_content(v: dict[str, Any], *, fill_text: bool = True) -> Content:
    st = v.get("statistics") or {}
    if not isinstance(st, dict):
        st = {}
    text, source = extract_text_and_source(v) if fill_text else ("", "")
    title = (v.get("desc") or "").strip() or None
    if title and len(title) > 80:
        title = title[:80]
    published_at: datetime | None = None
    create_time = v.get("create_time") or v.get("createTime")
    if isinstance(create_time, (int, float)) and create_time > 0:
        published_at = datetime.fromtimestamp(int(create_time), tz=UTC)
    duration_s: int | None = None
    video = v.get("video") or {}
    if isinstance(video, dict):
        dur = video.get("duration")
        if isinstance(dur, (int, float)):
            # Douyin often returns ms
            duration_s = int(dur // 1000) if dur > 1000 else int(dur)
    aweme_id = str(v.get("aweme_id") or v.get("awemeId") or "")
    return Content(
        platform="douyin",
        external_id=aweme_id,
        content_type="video",
        title=title,
        content=text or None,
        content_source=source,
        duration_s=duration_s,
        like_count=_as_int(st.get("digg_count")),
        comment_count=_as_int(st.get("comment_count")),
        share_count=_as_int(st.get("share_count")),
        collect_count=_as_int(st.get("collect_count")),
        published_at=published_at,
        raw=v,
    )


def _as_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    return None


class DouyinAdapter:
    platform: Platform = "douyin"

    def probe(self, client: TikHubHttpClient, account_key: str) -> AccountInfo:
        key = account_key.strip()
        payload = client.get(
            "/douyin/web/fetch_user_profile_by_short_id",
            {"short_id": key},
        )
        sec = _find_sec_uid(payload)
        if not sec:
            raise ValueError(f"响应中未找到 sec_uid: {str(payload)[:300]}")
        return AccountInfo(
            platform="douyin",
            account_key=key,
            external_id=sec,
            nickname=_find_first_str(payload, ("nickname", "nick_name")),
            avatar_url=_find_avatar_url(payload),
            follower_count=_find_first_int(payload, ("follower_count",)),
            total_favorited=_find_first_int(
                payload, ("total_favorited", "total_favorited_count")
            ),
            content_count=_find_first_int(
                payload, ("aweme_count", "video_count", "publish_count")
            ),
            raw=payload if isinstance(payload, dict) else {},
        )

    def fetch_recent(
        self,
        client: TikHubHttpClient,
        *,
        account_key: str,
        external_id: str,
        limit: int = _LIST_COUNT_DEFAULT,
    ) -> list[Content]:
        del account_key  # reserved for logging / future
        # ⚠️ 只拉第一页 — Task 52 采集策略;禁止翻页循环
        count = max(1, min(_LIST_COUNT_MAX, int(limit)))
        payload = client.get(
            "/douyin/web/fetch_user_post_videos",
            {
                "sec_user_id": external_id,
                "count": count,
                "max_cursor": 0,
            },
        )
        data = payload.get("data") or {}
        batch = data.get("aweme_list") or []
        if not isinstance(batch, list):
            return []
        out: list[Content] = []
        for v in batch:
            if isinstance(v, dict) and (v.get("aweme_id") or v.get("awemeId")):
                out.append(_aweme_to_content(v, fill_text=True))
            if len(out) >= count:
                break
        return out

    def fetch_detail(
        self,
        client: TikHubHttpClient,
        external_ids: list[str],
        *,
        sleep: Any = None,
    ) -> list[Content]:
        """Batch detail for desc-missing ids. Body MUST be a bare array."""
        _sleep = sleep if sleep is not None else time.sleep
        ids = [str(x) for x in external_ids if x]
        if not ids:
            return []
        out: list[Content] = []
        for i in range(0, len(ids), _DETAIL_CHUNK):
            chunk = ids[i : i + _DETAIL_CHUNK]
            # bare array — not {"items": [...]}
            payload = client.post_json(
                "/douyin/web/fetch_multi_video",
                chunk,
            )
            details = (payload.get("data") or {}).get("aweme_details") or []
            if isinstance(details, list):
                for v in details:
                    if isinstance(v, dict):
                        out.append(_aweme_to_content(v, fill_text=True))
            if i + _DETAIL_CHUNK < len(ids):
                _sleep(_DETAIL_SLEEP_S)
        return out


def enrich_missing_content(
    client: TikHubHttpClient,
    items: list[Content],
    *,
    adapter: DouyinAdapter | None = None,
    sleep: Any = time.sleep,
) -> list[Content]:
    """Call multi_video only when list-layer text is empty or <100 chars."""
    adapter = adapter or DouyinAdapter()
    missing = [
        c.external_id
        for c in items
        if c.external_id and (not c.content or len(c.content) < _DESC_MIN_LEN)
    ]
    if not missing:
        return items
    details = {
        d.external_id: d
        for d in adapter.fetch_detail(client, missing, sleep=sleep)
        if d.external_id
    }
    merged: list[Content] = []
    for c in items:
        d = details.get(c.external_id)
        if not d or not d.content:
            merged.append(c)
            continue
        if c.content and len(c.content) >= _DESC_MIN_LEN:
            merged.append(c)
            continue
        # Prefer detail text; keep list stats if detail omits them
        merged.append(
            Content(
                platform=c.platform,
                external_id=c.external_id,
                content_type=c.content_type,
                title=c.title or d.title,
                content=d.content,
                content_source=d.content_source or "subtitle",
                duration_s=d.duration_s or c.duration_s,
                like_count=c.like_count if c.like_count is not None else d.like_count,
                comment_count=(
                    c.comment_count if c.comment_count is not None else d.comment_count
                ),
                share_count=c.share_count if c.share_count is not None else d.share_count,
                collect_count=(
                    c.collect_count if c.collect_count is not None else d.collect_count
                ),
                published_at=c.published_at or d.published_at,
                raw=d.raw or c.raw,
            )
        )
    return merged
