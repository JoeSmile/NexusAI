"""Task 71 slice 2 — JWT secret strength gate."""

from __future__ import annotations

import pytest

from backend.core.auth.jwt_session import (
    JwtSecretError,
    assert_jwt_secret_strength,
    validate_jwt_secret_strength,
)


@pytest.mark.parametrize(
    "secret",
    [
        "short",
        "change-me",
        "change-me-wave-a-dev-only-min-32-bytes",
        "x" * 16,
    ],
)
def test_placeholder_or_short_secret_rejected(secret: str) -> None:
    with pytest.raises(JwtSecretError):
        validate_jwt_secret_strength(secret)


def test_assert_rejects_env_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "change-me-wave-a-dev-only-min-32-bytes")
    with pytest.raises(JwtSecretError):
        assert_jwt_secret_strength()
