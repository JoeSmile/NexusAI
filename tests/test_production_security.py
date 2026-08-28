"""Task 52 P0-1 — production env startup guard."""

from __future__ import annotations

import pytest

from packages.production_guard import ProductionConfigError, assert_production_security


def _strong() -> str:
    return "a" * 32 + "Z9!"


def test_non_production_skips_guard(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    assert_production_security()


def test_production_rejects_cors_allow_all(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("SECRET_KEY", _strong())
    monkeypatch.setenv("JWT_SECRET", _strong())
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ProductionConfigError, match="CORS_ALLOW_ALL"):
        assert_production_security()


def test_production_rejects_weak_jwt(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ALLOW_ALL", "false")
    monkeypatch.setenv("SECRET_KEY", _strong())
    monkeypatch.setenv("JWT_SECRET", "change-me-wave-a-dev-only-min-32-bytes")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ProductionConfigError, match="JWT_SECRET"):
        assert_production_security()


def test_prod_compose_does_not_open_cors_or_record() -> None:
    from pathlib import Path

    text = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    assert 'CORS_ALLOW_ALL: "false"' in text
    assert "LLM_PROVIDER: openai" in text
    assert "LLM_PROVIDER: record" not in text
    assert 'CORS_ALLOW_ALL: "true"' not in text
    assert "CORS_ALLOW_ALL: true" not in text


def test_uploads_not_served_as_static() -> None:
    from pathlib import Path

    text = Path("apps/api/app.py").read_text(encoding="utf-8")
    assert 'mount("/uploads"' not in text
    assert "StaticFiles(directory" in text  # playground only


def test_production_ok_with_strong_secrets(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ALLOW_ALL", "false")
    monkeypatch.setenv("SECRET_KEY", _strong())
    monkeypatch.setenv("JWT_SECRET", _strong())
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert_production_security()
