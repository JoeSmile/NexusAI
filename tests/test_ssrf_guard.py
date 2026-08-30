"""Task 71 slice 2 — SSRF guard matrix (default + SSRF_ALLOW_LOCAL_DEV)."""

from __future__ import annotations

import pytest

from packages.security.url_guard import UrlValidationError, validate_base_url


@pytest.fixture(autouse=True)
def _clear_ssrf_dev_flag(monkeypatch: pytest.MonkeyPatch) -> None:
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
    ],
)
def test_default_blocks_ssrf_targets(url: str) -> None:
    with pytest.raises(UrlValidationError):
        validate_base_url(url)


def test_default_allows_public_hostname() -> None:
    assert validate_base_url("https://api.openai.com/v1") == "https://api.openai.com/v1"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1"),
        ("http://localhost:11434/v1", "http://localhost:11434/v1"),
        ("http://10.0.0.1/v1", "http://10.0.0.1/v1"),
        ("http://192.168.1.1/v1", "http://192.168.1.1/v1"),
    ],
)
def test_allow_local_dev_permits_loopback_and_private(
    monkeypatch: pytest.MonkeyPatch, url: str, expected: str
) -> None:
    monkeypatch.setenv("SSRF_ALLOW_LOCAL_DEV", "1")
    assert validate_base_url(url) == expected


def test_allow_local_dev_still_blocks_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSRF_ALLOW_LOCAL_DEV", "1")
    with pytest.raises(UrlValidationError):
        validate_base_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(UrlValidationError):
        validate_base_url("http://metadata.google.internal/")
