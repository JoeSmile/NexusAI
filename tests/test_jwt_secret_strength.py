"""JWT_SECRET startup strength (Task 59 S6)."""

from __future__ import annotations

import pytest

from backend.core.auth.jwt_session import (
    JwtSecretError,
    assert_jwt_secret_strength,
    validate_jwt_secret_strength,
)


def test_validate_jwt_secret_strength_ok() -> None:
    validate_jwt_secret_strength("test-jwt-secret-wave-a-min-32-bytes!!")


@pytest.mark.parametrize(
    "secret",
    [
        "short",
        "change-me-wave-a-dev-only-min-32-bytes",
    ],
)
def test_validate_jwt_secret_strength_rejects(secret: str) -> None:
    with pytest.raises(JwtSecretError):
        validate_jwt_secret_strength(secret)


def test_assert_jwt_secret_strength_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "change-me-wave-a-dev-only-min-32-bytes")
    with pytest.raises(JwtSecretError, match="change-me"):
        assert_jwt_secret_strength()
