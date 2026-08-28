"""TikHubConnector — single entry for social fetch (Task 52 S1).

Key from env ``TIKHUB_API_KEY`` only (no hardcode). First wave: douyin.
"""

from __future__ import annotations

from typing import Any

from packages.social.adapters import get_adapter
from packages.social.adapters.douyin import enrich_missing_content
from packages.social.http_client import TikHubHttpClient, resolve_tikhub_api_key
from packages.social.types import AccountInfo, Content, Platform


class TikHubConnector:
    """Facade: probe / fetch_recent / fetch_detail across platform adapters."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: TikHubHttpClient | None = None,
        sleep: Any = None,
    ) -> None:
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            key = api_key if api_key is not None else resolve_tikhub_api_key()
            kwargs: dict[str, Any] = {"api_key": key}
            if sleep is not None:
                kwargs["sleep"] = sleep
            self._client = TikHubHttpClient(**kwargs)
            self._owns_client = True
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> TikHubConnector:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def probe(self, platform: Platform | str, account_key: str) -> AccountInfo:
        adapter = get_adapter(str(platform))
        return adapter.probe(self._client, account_key)

    def fetch_recent(
        self,
        platform: Platform | str,
        account_key: str,
        external_id: str,
        *,
        enrich: bool = True,
        limit: int = 20,
    ) -> list[Content]:
        adapter = get_adapter(str(platform))
        items = adapter.fetch_recent(
            self._client,
            account_key=account_key,
            external_id=external_id,
            limit=limit,
        )
        if not enrich or str(platform) != "douyin":
            return items
        if self._sleep is None:
            return enrich_missing_content(self._client, items)
        return enrich_missing_content(self._client, items, sleep=self._sleep)

    def fetch_detail(
        self,
        platform: Platform | str,
        external_ids: list[str],
    ) -> list[Content]:
        adapter = get_adapter(str(platform))
        return adapter.fetch_detail(
            self._client,
            external_ids,
            sleep=self._sleep,
        )
