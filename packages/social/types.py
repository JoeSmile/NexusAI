"""Unified social content schemas (Task 52)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Platform = Literal["douyin", "wechat_channels", "wechat_mp", "xiaohongshu"]
ContentType = Literal["video", "article", "image_text"]
ContentSource = Literal["desc", "caption", "subtitle", "whisper", "html", ""]


@dataclass(frozen=True)
class AccountInfo:
    platform: Platform
    account_key: str
    external_id: str
    nickname: str | None = None
    avatar_url: str | None = None
    follower_count: int | None = None
    total_favorited: int | None = None
    content_count: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Content:
    platform: Platform
    external_id: str
    content_type: ContentType = "video"
    title: str | None = None
    content: str | None = None
    content_source: ContentSource = ""
    duration_s: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    collect_count: int | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
