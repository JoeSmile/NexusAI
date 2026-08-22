"""SSRF guard for user-supplied base URLs (Task 59 S1)."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
    }
)
_METADATA_IPV4 = ipaddress.IPv4Address("169.254.169.254")


class UrlValidationError(ValueError):
    """Raised when a URL fails SSRF validation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _reject(code: str, message: str) -> None:
    raise UrlValidationError(code, message)


def _ip_is_ssrf_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip == _METADATA_IPV4:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
        return True
    # 裸 IP（含公网字面量）— 仅允许域名
    return True


def validate_base_url(url: str) -> str:
    """Validate and normalize a base URL. Raises UrlValidationError on SSRF risk."""
    raw = (url or "").strip()
    if not raw:
        _reject("url_empty", "url_empty")

    try:
        parsed = urlparse(raw)
    except ValueError:
        _reject("url_parse_failed", "url_parse_failed")

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        _reject("invalid_scheme", "invalid_scheme")

    host = parsed.hostname
    if not host:
        _reject("invalid_host", "invalid_host")

    host_lower = host.lower().rstrip(".")
    if host_lower in _BLOCKED_HOSTNAMES:
        _reject("ssrf_blocked", "ssrf_blocked")

    # IPv6 zone / bracket hosts are normalized by urlparse.hostname
    try:
        ip = ipaddress.ip_address(host_lower)
    except ValueError:
        ip = None
    else:
        if _ip_is_ssrf_blocked(ip):
            _reject("ssrf_blocked", "ssrf_blocked")

    # Reject obvious decimal / octal / hex IP encodings in hostname labels
    if re.fullmatch(r"\d+", host_lower) or re.fullmatch(r"0x[0-9a-f]+", host_lower):
        _reject("ssrf_blocked", "ssrf_blocked")

    normalized = f"{scheme}://{parsed.netloc}".rstrip("/")
    return normalized
