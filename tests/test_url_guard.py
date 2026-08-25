"""SSRF guard for base_url (Task 59 S1 / Task 71)."""

from __future__ import annotations

import pytest

from backend.core.security.url_guard import UrlValidationError, validate_base_url


@pytest.fixture(autouse=True)
def _clear_ssrf_dev_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate from developer config.env SSRF_ALLOW_LOCAL_DEV=1."""
    monkeypatch.delenv("SSRF_ALLOW_LOCAL_DEV", raising=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/v1",
        "http://localhost/v1",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",
        "https://8.8.8.8/v1",
        "ftp://api.example.com/v1",
        "not-a-url",
        "",
    ],
)
def test_validate_base_url_rejects_ssrf(url: str) -> None:
    with pytest.raises(UrlValidationError):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.openai.com/v1", "https://api.openai.com"),
        ("http://api.example.com", "http://api.example.com"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1/", "https://dashscope.aliyuncs.com"),
    ],
)
def test_validate_base_url_allows_public(url: str, expected: str) -> None:
    assert validate_base_url(url) == expected
