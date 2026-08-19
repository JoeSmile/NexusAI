"""Social / TikHub connector package (Task 52).

Lifecycle (拍板 A): use ``with TikHubConnector() as c:`` — no process singleton.
"""

from backend.core.social.connector import TikHubConnector
from backend.core.social.exceptions import (
    PlatformNotOpenError,
    TikHubBalanceError,
    TikHubConfigError,
    TikHubRateLimitError,
    TikHubUpstreamError,
)
from backend.core.social.types import AccountInfo, Content

__all__ = [
    "AccountInfo",
    "Content",
    "PlatformNotOpenError",
    "TikHubBalanceError",
    "TikHubConfigError",
    "TikHubConnector",
    "TikHubRateLimitError",
    "TikHubUpstreamError",
]
