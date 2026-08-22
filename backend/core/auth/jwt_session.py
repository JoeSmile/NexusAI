"""HS256 access-token issue/verify (Wave A / J0.5a).

Claims: sub, tid, role, jti, exp — no permission bags (evaluate at runtime).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

_ALG = "HS256"
_MIN_SECRET_LEN = 32
_FORBIDDEN_SUBSTR = "change-me"


class JwtSecretError(RuntimeError):
    """Raised when JWT_SECRET is missing or fails strength checks."""


def validate_jwt_secret_strength(secret: str) -> None:
    """Reject weak or placeholder secrets (Task 59 S6)."""
    s = (secret or "").strip()
    if len(s) < _MIN_SECRET_LEN:
        raise JwtSecretError(
            f"JWT_SECRET must be at least {_MIN_SECRET_LEN} characters "
            f"(got {len(s)}); generate with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if _FORBIDDEN_SUBSTR in s.lower():
        raise JwtSecretError(
            "JWT_SECRET contains forbidden placeholder 'change-me'; "
            "generate a strong random value"
        )


def assert_jwt_secret_strength() -> None:
    """Startup check — refuse boot with weak JWT_SECRET."""
    try:
        secret = _jwt_secret()
    except RuntimeError as exc:
        raise JwtSecretError(str(exc)) from exc
    validate_jwt_secret_strength(secret)


def _jwt_secret() -> str:
    """Read JWT_SECRET from env (or Settings). Do not reuse SECRET_KEY/LLM keys."""
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if secret:
        return secret
    try:
        from config import get_settings

        secret = (getattr(get_settings(), "jwt_secret", None) or "").strip()
    except Exception:
        secret = ""
    if not secret:
        raise RuntimeError(
            "JWT_SECRET is not set; add it to config.env / environment "
            "(separate from SECRET_KEY / LLM keys)"
        )
    return secret


def jwt_ttl_seconds() -> int:
    raw = os.getenv("JWT_TTL_SECONDS")
    if raw is not None and str(raw).strip() != "":
        return int(raw)
    try:
        from config import get_settings

        return int(getattr(get_settings(), "jwt_ttl_seconds", 3600) or 3600)
    except Exception:
        return 3600


def issue_access_token(*, sub: str, tid: str, role: str) -> str:
    """Issue a short-lived HS256 access token."""
    now = datetime.now(UTC)
    ttl = jwt_ttl_seconds()
    payload = {
        "sub": sub,
        "tid": tid,
        "role": role,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_ALG)


def verify_access_token(token: str) -> dict[str, Any]:
    """Verify token → claims dict. Raises ValueError on bad/expired token."""
    try:
        claims = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[_ALG],
            options={"require": ["sub", "tid", "role", "jti", "exp"]},
        )
    except ExpiredSignatureError as exc:
        raise ValueError("token_expired") from exc
    except InvalidTokenError as exc:
        raise ValueError("invalid_token") from exc

    for key in ("sub", "tid", "role", "jti"):
        if not claims.get(key):
            raise ValueError("invalid_token")
    return claims
