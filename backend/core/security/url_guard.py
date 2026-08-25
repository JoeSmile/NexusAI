"""SSRF guard for user-supplied base URLs (Task 59 S1)."""

from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
    }
)
_METADATA_IPV4 = ipaddress.IPv4Address("169.254.169.254")


def _dev_allow_local() -> bool:
    """本地开发放行开关（SSRF_ALLOW_LOCAL_DEV=1）：允许 loopback/私网地址，
    用于本地 Ollama / 内网服务调试。生产环境严禁开启。"""
    return os.getenv("SSRF_ALLOW_LOCAL_DEV", "").strip().lower() in ("1", "true", "yes")


class UrlValidationError(ValueError):
    """Raised when a URL fails SSRF validation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _reject(code: str, message: str) -> None:
    raise UrlValidationError(code, message)


def _ip_is_ssrf_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_local: bool = False) -> bool:
    if ip == _METADATA_IPV4:
        return True
    if allow_local and (ip.is_loopback or ip.is_private or ip.is_link_local):
        return False
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
        return True
    # 裸 IP（含公网字面量）— 仅允许域名
    return True


def validate_base_url(url: str) -> str:
    """Validate and normalize a base URL. Raises UrlValidationError on SSRF risk."""
    allow_local = _dev_allow_local()
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
        # 本地开发：放行 localhost（metadata 永远拦）
        if not (allow_local and host_lower == "localhost"):
            _reject("ssrf_blocked", "ssrf_blocked")

    # IPv6 zone / bracket hosts are normalized by urlparse.hostname
    try:
        ip = ipaddress.ip_address(host_lower)
    except ValueError:
        ip = None
    else:
        if _ip_is_ssrf_blocked(ip, allow_local=allow_local):
            _reject("ssrf_blocked", "ssrf_blocked")

    # Reject obvious decimal / octal / hex IP encodings in hostname labels
    if re.fullmatch(r"\d+", host_lower) or re.fullmatch(r"0x[0-9a-f]+", host_lower):
        _reject("ssrf_blocked", "ssrf_blocked")

    normalized = f"{scheme}://{parsed.netloc}".rstrip("/")
    return normalized
