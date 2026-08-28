"""Social / TikHub connector package (Task 52).

Lifecycle (拍板 A): use ``with TikHubConnector() as c:`` — no process singleton.
"""

from packages.social.connector import TikHubConnector
from packages.social.exceptions import (
    PlatformNotOpenError,
    TikHubBalanceError,
    TikHubConfigError,
    TikHubRateLimitError,
    TikHubUpstreamError,
)
from packages.social.types import AccountInfo, Content

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
