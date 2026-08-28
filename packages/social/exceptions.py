"""TikHub / social connector errors (Task 52 S1)."""

from __future__ import annotations

TIKHUB_TOPUP_URL = "https://user.tikhub.io/users/add_credit"


class SocialError(Exception):
    """Base for social connector failures."""


class TikHubConfigError(SocialError):
    """Missing or invalid TIKHUB_API_KEY."""


class TikHubBalanceError(SocialError):
    """HTTP/body 402 — TikHub credit exhausted."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or f"TikHub 余额不足:去 {TIKHUB_TOPUP_URL} 充值"
        )
        self.topup_url = TIKHUB_TOPUP_URL


class SocialCostAlertError(SocialError):
    """SOCIAL_COST_ALERT_USD exceeded — refuse new analysis-tasks (402-style)."""

    http_status = 402

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "社媒采集成本告警阈值已达，暂停新建分析任务"
        )


class TikHubUpstreamError(SocialError):
    """Upstream non-success after retries (or non-retryable failure)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PlatformNotOpenError(SocialError):
    """Platform listed in UI but adapter not implemented yet."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        super().__init__(f"平台暂未开放: {platform}")


class TikHubRateLimitError(SocialError):
    """Token-bucket wait exceeded — map to HTTP 429 for API probe."""

    http_status = 429

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "TikHub 限流，请稍后重试")


class TikHubRateLimitTimeout(SocialError):
    """Worker acquire timed out — requeue pending until retry_count cap."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "tikhub_rate_limit_timeout")
