"""Platform adapter registry."""

from __future__ import annotations

from backend.core.social.adapters.base import PlatformAdapter
from backend.core.social.adapters.douyin import DouyinAdapter
from backend.core.social.exceptions import PlatformNotOpenError


def get_adapter(platform: str) -> PlatformAdapter:
    if platform == "douyin":
        return DouyinAdapter()
    raise PlatformNotOpenError(platform)
