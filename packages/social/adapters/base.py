"""Platform adapter protocol (Task 52)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from packages.social.http_client import TikHubHttpClient
from packages.social.types import AccountInfo, Content, Platform


class PlatformAdapter(Protocol):
    platform: Platform

    def probe(self, client: TikHubHttpClient, account_key: str) -> AccountInfo: ...

    def fetch_recent(
        self,
        client: TikHubHttpClient,
        *,
        account_key: str,
        external_id: str,
        limit: int = 20,
    ) -> list[Content]: ...

    def fetch_detail(
        self,
        client: TikHubHttpClient,
        external_ids: list[str],
        *,
        sleep: Callable[[float], None] | None = None,
    ) -> list[Content]: ...
