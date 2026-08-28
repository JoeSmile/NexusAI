"""Production boot-time security checks (Task 52 P0-1).

Refuse to start when ENVIRONMENT/APP_ENV=production and CORS is open
or secrets are placeholders. Dev/test are unaffected.
"""

from __future__ import annotations

import os

_WEAK_MARKERS = ("change-me", "changeme", "dev-only", "please-change")
_FORBIDDEN_LLM = frozenset({"record", "replay", "mock"})


class ProductionConfigError(RuntimeError):
    """Raised when production env would boot in an unsafe configuration."""


def _is_production() -> bool:
    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    return env == "production"


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def _secret_problem(name: str) -> str | None:
    raw = (os.getenv(name) or "").strip()
    if len(raw) < 32:
        return f"{name} must be at least 32 characters"
    low = raw.lower()
    if any(m in low for m in _WEAK_MARKERS):
        return f"{name} looks like a placeholder; generate with python secrets"
    return None


def assert_production_security() -> None:
    """No-op unless production. Raises ProductionConfigError with all findings."""
    if not _is_production():
        return
    errors: list[str] = []
    if _truthy(os.getenv("CORS_ALLOW_ALL")):
        errors.append("CORS_ALLOW_ALL=true is forbidden in production")
    for name in ("SECRET_KEY", "JWT_SECRET"):
        problem = _secret_problem(name)
        if problem:
            errors.append(problem)
    if _truthy(os.getenv("LANGFUSE_ENABLED")):
        problem = _secret_problem("SALT")
        if problem:
            errors.append(problem)
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider in _FORBIDDEN_LLM:
        errors.append(
            f"LLM_PROVIDER={provider} is forbidden in production; set LLM_PROVIDER=openai"
        )
    if errors:
        raise ProductionConfigError(
            "production security check failed: " + "; ".join(errors)
        )
