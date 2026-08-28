"""Platform adapter registry."""

from __future__ import annotations

from packages.social.adapters.base import PlatformAdapter
from packages.social.adapters.douyin import DouyinAdapter
from packages.social.exceptions import PlatformNotOpenError


def get_adapter(platform: str) -> PlatformAdapter:
    if platform == "douyin":
        return DouyinAdapter()
    raise PlatformNotOpenError(platform)
