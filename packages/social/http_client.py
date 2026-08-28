"""TikHub HTTP client — httpx + curl UA + exponential backoff (Task 52 S1).

API facts (2026-08-17, write into callers as comments too):
- UA must be ``curl/8.7.1`` (Python-urllib → 403, Mozilla → 400)
- Body 402 / HTTP 402 → balance; 429 / 400 "Please retry" → backoff
- multi_video_v2 POST body is a bare JSON array, not ``{"items": [...]}``
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from packages.social.exceptions import (
    TikHubBalanceError,
    TikHubConfigError,
    TikHubUpstreamError,
)

logger = logging.getLogger(__name__)

API_BASE = "https://api.tikhub.dev/api/v1"
CURL_UA = "curl/8.7.1"
DEFAULT_TIMEOUT = 25.0
MAX_RETRY = 6
# 3 / 6 / 12 / 24 / 48 / 96s — matches edu-content-pipeline stable v2
_BACKOFF_BASE_S = 3.0


def resolve_tikhub_api_key() -> str:
    key = (os.environ.get("TIKHUB_API_KEY") or "").strip()
    if not key:
        raise TikHubConfigError("缺少 TIKHUB_API_KEY 环境变量")
    return key


def _is_402(payload: Any, status_code: int | None) -> bool:
    if status_code == 402:
        return True
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict) and detail.get("code") == 402:
            return True
    return False


def _should_retry(payload: Any, status_code: int | None) -> bool:
    if status_code in (429, 500, 502, 503, 504):
        return True
    if status_code == 400 and isinstance(payload, dict):
        # TikHub wind-control: 400 + "Please retry"
        blob = str(payload).lower()
        if "please retry" in blob or "retry" in blob:
            return True
    if isinstance(payload, dict) and payload.get("_parse_fail"):
        return True
    return False


class TikHubHttpClient:
    """Sync httpx client with TikHub-required headers and retries."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = API_BASE,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        sleep: Any = time.sleep,
        max_retry: int = MAX_RETRY,
    ) -> None:
        self._api_key = api_key if api_key is not None else resolve_tikhub_api_key()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._sleep = sleep
        self._max_retry = max_retry
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": CURL_UA,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TikHubHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post_json(self, path: str, body: Any) -> dict[str, Any]:
        """POST JSON body as-is (list or dict). Bare arrays required for multi_video_v2."""
        return self._request("POST", path, json_body=body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        attempt: int = 0,
    ) -> dict[str, Any]:
        if not path.startswith("/"):
            path = "/" + path
        try:
            if method == "GET":
                resp = self._client.get(path, params=params)
            else:
                resp = self._client.post(
                    path,
                    json=json_body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            if attempt >= self._max_retry:
                raise TikHubUpstreamError(f"TikHub 网络错误: {exc}") from exc
            wait = _BACKOFF_BASE_S * (2**attempt)
            logger.warning(
                "tikhub http error attempt=%s wait=%.0fs err=%s",
                attempt + 1,
                wait,
                exc,
            )
            self._sleep(wait)
            return self._request(
                method, path, params=params, json_body=json_body, attempt=attempt + 1
            )

        status = resp.status_code
        try:
            payload: Any = resp.json()
        except ValueError:
            payload = {"_parse_fail": (resp.text or "")[:200]}

        if _is_402(payload, status):
            raise TikHubBalanceError()

        if isinstance(payload, dict) and payload.get("code") == 200:
            return payload

        if _should_retry(payload, status) and attempt < self._max_retry:
            wait = _BACKOFF_BASE_S * (2**attempt)
            logger.warning(
                "tikhub retry attempt=%s path=%s status=%s wait=%.0fs body=%s",
                attempt + 1,
                path,
                status,
                wait,
                str(payload)[:120],
            )
            self._sleep(wait)
            return self._request(
                method, path, params=params, json_body=json_body, attempt=attempt + 1
            )

        raise TikHubUpstreamError(
            f"TikHub 请求失败: status={status} body={str(payload)[:200]}",
            status_code=status,
        )
